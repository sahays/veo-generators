"""Location layout estimation: one VLM read of the plate -> deterministic 3D set.

The VLM reports, per set piece, its kind, a tight image box [x0, y0, x1, y1], its plate x
and relative depth (0 near .. 1 far), plus the room size / colours and every door and
window (wall + box). Everything after that is pure: the piece is typed (`kinds`: name /
description keyword rules first, the VLM kind as fallback), the box bottom is cast onto
the floor through the master camera for the front depth (else the relative depth maps
between the nearest visible floor and the back wall), the size is kind default x sheet
aspect x plate footprint (`proportions`), plate x maps to world X, pieces are clamped and
pushed apart along X, and doors / windows are mounted on their walls (`openings`). The
plate's stored layout x wins over the VLM's x so the 2D keyframes and the 3D set agree.
A calibrated master camera / room from the camera stage replace the synthetic ones.
`source_hash` keys the cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, Field

from ...adapters.base import VLMProvider
from ...keyframes.plan.models import ObjectInput
from ...keyframes.render.retry import with_retry
from ...schemas.previz_scene import (
    CameraRig,
    LocationLayout,
    PieceKind,
    Room,
    SetPiece,
    Vec3,
)
from ..blocking.project import Aspect, MasterCamera, floor_start, master_camera, world_x
from .colors import hash_color
from .kinds import Classified, classify
from .openings import OpeningObs, place_opening, place_openings
from .place import resolve_overlaps
from .proportions import BBox, from_box_2d, measure, shape_for
from .stacking import stacked_piece, supporter_of

_log = logging.getLogger(__name__)
ESTIMATOR_VERSION: Final[str] = "layout-v3"
_ITEM_RE = re.compile(r"^- (.+)$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
NEAR_MARGIN: Final[float] = 0.2
BACK_MARGIN: Final[float] = 0.05
UNSEEN_DEPTH: Final[float] = 0.85  # pieces the VLM could not locate stand near the back
BOX_X_TOL: Final[float] = 0.15  # box centre vs VLM x disagreement that voids the box
WALL_KINDS: Final[frozenset[str]] = frozenset({"door", "window"})
KIND_NAMES: Final[str] = (
    "cabinet, chest, bench, table, shelf, stool, door, window, toolbox, box, cylinder"
)


class PieceObs(BaseModel):
    name: str
    kind: PieceKind | None = None
    box_2d: list[float] | None = None  # [ymin, xmin, ymax, xmax] in 0..1000 (Gemini)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    depth: float = Field(default=0.7, ge=0.0, le=1.0)


class RoomObs(BaseModel):
    width_m: float = 8.0
    depth_m: float = 6.0
    height_m: float = 3.0
    floor_color: str = ""
    wall_color: str = ""


class LayoutObs(BaseModel):
    room: RoomObs = Field(default_factory=RoomObs)
    pieces: list[PieceObs] = Field(default_factory=list)
    openings: list[OpeningObs] = Field(default_factory=list)

    @classmethod
    def mock_response(cls, prompt: str) -> LayoutObs:
        names = listed(prompt)
        step = 1 / (len(names) + 1)
        return cls(
            pieces=[
                PieceObs(name=n, x=round((i + 1) * step, 3), depth=0.8)
                for i, n in enumerate(names)
            ]
        )


def listed(prompt: str) -> list[str]:
    return [
        m.group(1).strip() for ln in prompt.splitlines() if (m := _ITEM_RE.match(ln))
    ]


@dataclass(frozen=True)
class LayoutRequest:
    location_id: str
    name: str
    description: str = ""
    location_ref_uri: str | None = None
    plate_png: bytes | None = None
    plate_layout_x: Mapping[str, float] = field(default_factory=dict)
    set_pieces: Sequence[ObjectInput] = ()
    ref_colors: Mapping[str, str] = field(default_factory=dict)
    aspect: Aspect = "16:9"
    ref_aspects: Mapping[str, float] = field(default_factory=dict)  # sheet width/height
    master: CameraRig | None = None  # calibrated plate camera (camera stage)
    room: Room | None = None  # calibrated room dimensions (camera stage)


def source_hash(req: LayoutRequest) -> str:
    """sha256 of every input that determines the layout (order-independent)."""
    body = {
        "v": ESTIMATOR_VERSION,
        "loc": [req.location_id, req.name, req.description, req.location_ref_uri],
        "plate": hashlib.sha256(req.plate_png).hexdigest() if req.plate_png else "",
        "plate_x": sorted(req.plate_layout_x.items()),
        "pieces": sorted(
            (o.entity_id, o.name, o.description, o.ref_uri or "")
            for o in req.set_pieces
        ),
        "colors": sorted(req.ref_colors.items()),
        "aspect": req.aspect,
        "ref_aspects": sorted(req.ref_aspects.items()),
        "master": req.master.model_dump_json() if req.master else "",
        "room": req.room.model_dump_json() if req.room else "",
    }
    return hashlib.sha256(json.dumps(body).encode("utf-8")).hexdigest()


def layout_prompt(req: LayoutRequest, on_plate: bool) -> str:
    what = "the empty scene plate" if on_plate else "the location reference sheet"
    items = "\n".join(f"- {o.name}" for o in req.set_pieces)
    return (
        f"The image is {what} of '{req.name}': {req.description}\n"
        "Estimate the room: width_m, depth_m, height_m (metres) and floor_color, "
        "wall_color as #rrggbb. For each item below report: name (exact), kind (one of: "
        f"{KIND_NAMES}), box_2d = the tight box around the item as [ymin, xmin, ymax, "
        "xmax] normalised to 0-1000 (null if not visible), x = its horizontal centre "
        "(0 = left edge, 1 = right edge; null if not visible) and depth = how far "
        "from the camera it stands (0 = nearest floor, 1 = against the back wall). Also "
        "list under openings every door and window visible in the image or named in the "
        "description that is not an item below: kind (door or window), wall (back, left "
        "or right) and box_2d. Use the exact item names:\n" + items
    )


def _room(obs: RoomObs, override: Room | None) -> Room:
    def clamp(v: float, lo: float, hi: float) -> float:
        return round(min(max(v, lo), hi), 3)

    base = override or Room(
        width=clamp(obs.width_m, 4.0, 16.0),
        depth=clamp(obs.depth_m, 3.0, 12.0),
        height=clamp(obs.height_m, 2.4, 5.0),
    )
    return base.model_copy(
        update={
            "floor_color": obs.floor_color
            if _HEX_RE.match(obs.floor_color)
            else base.floor_color,
            "wall_color": obs.wall_color
            if _HEX_RE.match(obs.wall_color)
            else base.wall_color,
        }
    )


def _seen_box(seen: PieceObs | None) -> BBox | None:
    """The VLM box, dropped when its centre contradicts the VLM's own x answer."""
    box = from_box_2d(seen.box_2d) if seen else None
    if box is None or seen is None or seen.x is None:
        return box
    return box if abs((box[0] + box[2]) / 2 - seen.x) <= BOX_X_TOL else None


def _seen_x(seen: PieceObs | None) -> float | None:
    if seen is None:
        return None
    box = _seen_box(seen)
    return seen.x if seen.x is not None else ((box[0] + box[2]) / 2 if box else None)


def _image_xs(req: LayoutRequest, obs: Mapping[str, PieceObs]) -> dict[str, float]:
    """Plate x per piece: stored plate layout > VLM x / box > even spread of the rest."""
    known: dict[str, float] = {}
    for o in req.set_pieces:
        x = req.plate_layout_x.get(o.entity_id, _seen_x(obs.get(o.name.lower())))
        if x is not None:
            known[o.entity_id] = x
    missing = sorted(o.entity_id for o in req.set_pieces if o.entity_id not in known)
    step = 1 / (len(missing) + 1)
    return known | {eid: round((i + 1) * step, 3) for i, eid in enumerate(missing)}


@dataclass(frozen=True)
class _Ctx:
    req: LayoutRequest
    room: Room
    cam: MasterCamera
    near: float


def _relative_front(ctx: _Ctx, eid: str, seen: PieceObs | None, depth: float) -> float:
    """Front depth from the VLM's relative depth (unlocated pieces near the back wall)."""
    located = seen is not None and (
        _seen_x(seen) is not None or eid in ctx.req.plate_layout_x
    )
    frac = seen.depth if located and seen is not None else UNSEEN_DEPTH
    lo, hi = ctx.near, ctx.room.depth - depth - BACK_MARGIN
    return lo + (hi - lo) * frac if hi > lo else hi


def _floor_piece(
    ctx: _Ctx, o: ObjectInput, seen: PieceObs | None, cls: Classified, x_img: float
) -> SetPiece:
    box = _seen_box(seen)
    fallback = _relative_front(ctx, o.entity_id, seen, cls.dims[1])
    fp = measure(ctx.cam, box, fallback, cls.dims[1]) if box else None
    aspect = ctx.req.ref_aspects.get(o.entity_id)
    shaped = shape_for(cls, o.description, aspect, fp, ctx.room)
    size = shaped.size
    front = fp.front_y if fp is not None and fp.front_y is not None else fallback
    lo, hi = ctx.near + size.y / 2, ctx.room.depth - size.y / 2 - BACK_MARGIN
    y = min(max(front + size.y / 2, lo), hi) if hi > lo else hi
    return SetPiece(
        entity_id=o.entity_id,
        name=o.name,
        shape=shaped.shape,
        kind=shaped.kind,
        params=shaped.params,
        position=Vec3(
            x=round(world_x(ctx.cam, x_img, y, size.z / 2), 3), y=round(y, 3)
        ),
        size=size,
        color=ctx.req.ref_colors.get(o.entity_id) or hash_color(o.entity_id),
    )


def _wall_piece(
    ctx: _Ctx, o: ObjectInput, seen: PieceObs | None, kind: str
) -> SetPiece:
    """A listed set piece that is itself a door / window: mounted on the back wall."""
    obs = OpeningObs(
        kind="door" if kind == "door" else "window",
        box_2d=seen.box_2d if seen else None,
    )
    piece = place_opening(ctx.room, ctx.cam, obs, o.entity_id, o.name)
    color = ctx.req.ref_colors.get(o.entity_id)
    return piece.model_copy(update={"color": color}) if color else piece


Stack = list[tuple[ObjectInput, Classified, BBox, str]]


def _typed(
    req: LayoutRequest, by_name: Mapping[str, PieceObs]
) -> list[tuple[ObjectInput, PieceObs | None, Classified]]:
    out: list[tuple[ObjectInput, PieceObs | None, Classified]] = []
    for o in sorted(req.set_pieces, key=lambda s: s.entity_id):
        seen = by_name.get(o.name.lower())
        out.append(
            (o, seen, classify(o.name, o.description, seen.kind if seen else None))
        )
    return out


def _split(
    ctx: _Ctx, by_name: Mapping[str, PieceObs]
) -> tuple[list[SetPiece], Stack, list[SetPiece]]:
    """(floor pieces, pieces standing on a floor piece, wall-mounted pieces)."""
    typed = _typed(ctx.req, by_name)
    boxes = {
        o.entity_id: b
        for o, seen, cls in typed
        if cls.kind not in WALL_KINDS and (b := _seen_box(seen)) is not None
    }
    xs = _image_xs(ctx.req, by_name)
    floor: list[SetPiece] = []
    stack: Stack = []
    walls: list[SetPiece] = []
    for o, seen, cls in typed:
        sup = supporter_of(o.entity_id, boxes) if o.entity_id in boxes else None
        if sup is not None and supporter_of(sup, boxes) is not None:
            sup = None  # no towers: a piece on a stacked piece is placed on the floor
        if cls.kind in WALL_KINDS:
            walls.append(_wall_piece(ctx, o, seen, cls.kind))
        elif sup is not None:
            stack.append((o, cls, boxes[o.entity_id], sup))
        else:
            floor.append(_floor_piece(ctx, o, seen, cls, xs[o.entity_id]))
    return floor, stack, walls


def _stacked(ctx: _Ctx, stack: Stack, placed: list[SetPiece]) -> list[SetPiece]:
    by_id = {p.entity_id: p for p in placed}
    out: list[SetPiece] = []
    for o, cls, box, sid in stack:
        sup = by_id.get(sid)
        if sup is None:  # unreachable: supporters are always floor pieces
            continue
        aspect = ctx.req.ref_aspects.get(o.entity_id)
        color = ctx.req.ref_colors.get(o.entity_id) or hash_color(o.entity_id)
        out.append(stacked_piece(ctx.cam, ctx.room, (o, cls, box, aspect), sup, color))
    return out


def build_layout(req: LayoutRequest, obs: LayoutObs) -> LocationLayout:
    """Pure: VLM observation + inputs -> typed, sized, overlap-free `LocationLayout`."""
    room = _room(obs.room, req.room)
    cam = master_camera(room, req.aspect, req.master)
    ctx = _Ctx(req, room, cam, floor_start(cam, room) + NEAR_MARGIN)
    floor, stack, walls = _split(ctx, {p.name.lower(): p for p in obs.pieces})
    placed = resolve_overlaps(floor, room)
    walls += place_openings(req.location_id, room, cam, obs.openings, req.description)
    pieces = placed + _stacked(ctx, stack, placed) + walls
    return LocationLayout(
        location_id=req.location_id,
        name=req.name,
        room=room,
        set_pieces=sorted(pieces, key=lambda p: p.entity_id),
        source_hash=source_hash(req),
    )


def _log_kinds(req: LayoutRequest, layout: LocationLayout) -> None:
    _log.info(
        "previz_layout_built",
        extra={
            "who": "storygraph.previz",
            "where": "previz.layout.estimate",
            "what": ", ".join(f"{p.name}={p.kind}" for p in layout.set_pieces),
            "when": datetime.now(UTC).isoformat(),
            "why": f"layout for location {req.location_id}",
            "how": "keyword/VLM typing x sheet aspect x plate footprint",
        },
    )


class LayoutEstimator:
    """ONE VLM call per estimate (plate preferred, else the location sheet)."""

    def __init__(self, vlm: VLMProvider, fetch: Callable[[str], bytes]) -> None:
        self.vlm, self.fetch = vlm, fetch

    def observe(self, req: LayoutRequest) -> LayoutObs:
        image = req.plate_png or (
            self.fetch(req.location_ref_uri) if req.location_ref_uri else None
        )
        prompt = layout_prompt(req, req.plate_png is not None)
        images = [image] if image else []
        return with_retry(
            lambda: self.vlm.review(images, prompt, LayoutObs), "previz.layout"
        )

    def estimate_request(self, req: LayoutRequest) -> LocationLayout:
        layout = build_layout(req, self.observe(req))
        _log_kinds(req, layout)
        return layout

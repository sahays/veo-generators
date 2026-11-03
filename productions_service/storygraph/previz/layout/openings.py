"""Wall-mounted doors and windows (pure): VLM image boxes -> SetPieces on the right wall.

Each observed opening names its wall (back / left / right) and an image box (Gemini's
native `box_2d` = [ymin, xmin, ymax, xmax] in 0..1000). Its pixel
rays are intersected with that wall's plane through the master camera: on the back wall
(Y = depth) the box's x extent gives X and the box rows give the vertical span; on a side
wall (X = -/+ W/2) the box's x extent gives the span along Y and the piece is turned 90°.
A door stands on the floor (height from the box, 1.9-2.4 m); a window gets its sill
height in `params["sill_z"]` and `size.z` is the opening height. Unusable boxes fall back
to the kind's default size at a stable spot on that wall. If the location description
mentions a door / window that the VLM did not report, one default opening is added on the
back wall (door left of centre, window right of centre), so the text is always honoured.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, Literal

from pydantic import BaseModel

from ...schemas.previz_scene import Room, SetPiece, Vec3
from ..blocking.project import Axis, MasterCamera, hit_plane
from .kinds import DEFAULT_DIMS
from .proportions import BBox, from_box_2d

Wall = Literal["back", "left", "right"]
OpeningKind = Literal["door", "window"]
THICK: Final[float] = 0.08
SILL: Final[float] = 0.9
EDGE: Final[float] = 0.1
_DEFAULT_X: Final[dict[str, float]] = {"door": -0.25, "window": 0.25}  # x room width
_COLOR: Final[dict[str, str]] = {"door": "#7a5230", "window": "#a8c8e0"}


class OpeningObs(BaseModel):
    kind: OpeningKind
    wall: Wall = "back"
    box_2d: list[float] | None = None  # [ymin, xmin, ymax, xmax] in 0..1000 (Gemini)


def _span(lo: float, hi: float, length: float, limit: float) -> tuple[float, float]:
    """Centre / width of [lo, hi] (0.4-2x the kind's `length`, which is also the
    default) kept inside +-limit."""
    measured = min(max(hi - lo, 0.4 * length), 2.0 * length)
    width = min(measured, 2 * limit - 2 * EDGE) if hi > lo else length
    centre = min(
        max((lo + hi) / 2, -limit + EDGE + width / 2), limit - EDGE - width / 2
    )
    return round(centre, 3), round(width, 3)


def _vertical(
    kind: OpeningKind, cam: MasterCamera, box: BBox | None, axis: Axis, value: float
) -> tuple[float, float]:
    """(bottom z, height) on the wall plane from the box rows (defaults if unusable).
    On a side wall the box's outer column is the opening's NEAR edge, which spans the
    box's full height under perspective; on the back wall the centre column is used."""
    top = low = None
    if box is not None:
        col = (box[0] + box[2]) / 2 if axis == 1 else (box[0] if value < 0 else box[2])
        top = hit_plane(cam, col, box[1], axis, value)
        low = hit_plane(cam, col, box[3], axis, value)
    if kind == "door":
        h = top.z if top else DEFAULT_DIMS["door"][2]
        return 0.0, round(min(max(h, 1.9), 2.4), 3)
    sill = min(max(low.z, 0.3), 1.6) if low else SILL
    h = (top.z - sill) if top else DEFAULT_DIMS["window"][2]
    return round(sill, 3), round(min(max(h, 0.4), 2.0), 3)


def _extent(
    cam: MasterCamera, box: BBox | None, axis: Axis, value: float
) -> tuple[float, float]:
    """Along-wall coordinate range of the box's left/right edges at mid height."""
    if box is None:
        return 0.0, 0.0
    ym = (box[1] + box[3]) / 2
    a, b = (
        hit_plane(cam, box[0], ym, axis, value),
        hit_plane(cam, box[2], ym, axis, value),
    )
    if a is None or b is None:
        return 0.0, 0.0
    pa, pb = (a.x, b.x) if axis == 1 else (a.y, b.y)
    return min(pa, pb), max(pa, pb)


def place_opening(
    room: Room, cam: MasterCamera, obs: OpeningObs, entity_id: str, name: str
) -> SetPiece:
    kind, box = obs.kind, from_box_2d(obs.box_2d)
    side = {"left": -1.0, "right": 1.0}.get(obs.wall, 0.0)
    axis: Axis = 1 if side == 0.0 else 0
    value = room.depth if side == 0.0 else side * room.width / 2
    lo, hi = _extent(cam, box, axis, value)
    limit = room.width / 2 if side == 0.0 else room.depth / 2
    offset = 0.0 if side == 0.0 else room.depth / 2
    default_c = _DEFAULT_X[kind] * room.width if side == 0.0 else 0.0
    if hi <= lo:
        lo = hi = default_c + offset
    centre, width = _span(lo - offset, hi - offset, DEFAULT_DIMS[kind][0], limit)
    bottom, height = _vertical(kind, cam, box, axis, value)
    if side == 0.0:
        pos = Vec3(x=centre, y=round(room.depth - THICK / 2, 3), z=0.0)
    else:
        pos = Vec3(
            x=round(value - side * THICK / 2, 3), y=round(centre + offset, 3), z=0.0
        )
    return SetPiece(
        entity_id=entity_id, name=name, kind=kind, position=pos,
        size=Vec3(x=width, y=THICK, z=height), rotation_z_deg=90.0 if side else 0.0,
        params={"sill_z": bottom} if kind == "window" else {}, color=_COLOR[kind],
    )  # fmt: skip


def mentioned(description: str, kind: OpeningKind) -> bool:
    return re.search(rf"\b{kind}s?\b", description.lower()) is not None


def place_openings(
    location_id: str,
    room: Room,
    cam: MasterCamera,
    observed: Sequence[OpeningObs],
    description: str,
) -> list[SetPiece]:
    """Observed openings plus one default per kind the description mentions but the VLM
    missed. Ids are `<location>__<kind>_<n>` (stable for a given observation order)."""
    wanted = list(observed) + [
        OpeningObs(kind=k)
        for k in ("door", "window")
        if mentioned(description, k) and not any(o.kind == k for o in observed)
    ]
    counts: dict[str, int] = {}
    out: list[SetPiece] = []
    for obs in wanted:
        counts[obs.kind] = counts.get(obs.kind, 0) + 1
        n = counts[obs.kind]
        eid = f"{location_id}__{obs.kind}_{n}"
        out.append(place_opening(room, cam, obs, eid, f"{obs.kind.title()} {n}"))
    return out

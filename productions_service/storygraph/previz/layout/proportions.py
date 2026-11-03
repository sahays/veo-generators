"""Real proportions (pure): type default x sheet aspect x plate footprint -> metres.

`measure` turns the layout VLM's per-piece image box [x0, y0, x1, y1] (0..1) into metres
through the master camera: the box bottom is the front edge on the floor (ray / floor
hit -> front depth, unless the box is cut by the frame bottom), the horizontal extent at
that depth is the width, and the box top on the front plane is the height (re-cast on the
back plane when the camera looks down on the top, since then the top edge seen is the
back one). `piece_size` blends: the sheet's subject aspect (bounded to +-25 % of the type
ratio, then geometrically averaged with it: sheets are cluttered photos) fixes width /
height; the plate
height and the plate width / aspect are averaged into the height; the kind's default size
bounds everything (0.5-2x height, 0.4-2.5x width), so a cabinet can never become a locker.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from ...keyframes.plan.models import ObjectInput
from ...schemas.previz_scene import PieceKind, Room, Shape, Vec3
from ..blocking.project import MasterCamera, hit_plane, world_x
from .kinds import Classified, Dims, classify, kind_params

BBox = tuple[float, float, float, float]
CUT: Final[float] = 0.985  # box bottom below this row: floor contact out of frame
MIN_BOX: Final[float] = 0.01
ASPECT_SPAN: Final[float] = 1.25  # sheets are cluttered photos: weak evidence only


@dataclass(frozen=True)
class Footprint:
    front_y: float | None  # floor depth of the front face (None: contact not visible)
    width_m: float
    height_m: float


@dataclass(frozen=True)
class Shaped:
    kind: PieceKind
    shape: Shape
    size: Vec3
    params: dict[str, float] = field(default_factory=dict)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def from_box_2d(raw: Sequence[float] | None) -> BBox | None:
    """Gemini's native box `[ymin, xmin, ymax, xmax]` (0..1000, or 0..1) -> `BBox`."""
    if raw is None or len(raw) != 4:
        return None
    scale = 1000.0 if max(raw) > 1.5 else 1.0
    y0, x0, y1, x1 = (float(v) / scale for v in raw)
    return clean_bbox((x0, y0, x1, y1))


def clean_bbox(raw: Sequence[float] | None) -> BBox | None:
    """A sane [x0, y0, x1, y1] in 0..1 (corners sorted), else None."""
    if raw is None or len(raw) != 4:
        return None
    x0, y0, x1, y1 = (_clamp(float(v), 0.0, 1.0) for v in raw)
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return (x0, y0, x1, y1) if x1 - x0 > MIN_BOX and y1 - y0 > MIN_BOX else None


def _top_z(
    cam: MasterCamera, xc: float, y0: float, front: float, depth: float
) -> float:
    hit = hit_plane(cam, xc, y0, 1, front)
    if hit is None:
        return 0.0
    if cam.position.z <= hit.z:
        return hit.z
    back = hit_plane(cam, xc, y0, 1, front + depth)
    return back.z if back is not None else hit.z


def measure(
    cam: MasterCamera, box: BBox, fallback_y: float, depth: float, on_floor: bool = True
) -> Footprint:
    """Metric footprint of an image box (`fallback_y` = front depth if the floor contact
    is unseen or the piece stands on another piece: `on_floor=False`)."""
    x0, y0, x1, y1 = box
    xc = (x0 + x1) / 2
    floor = hit_plane(cam, xc, y1, 2, 0.0) if on_floor and y1 < CUT else None
    front = floor.y if floor is not None else fallback_y
    width = abs(world_x(cam, x1, front, 0.0) - world_x(cam, x0, front, 0.0))
    height = max(_top_z(cam, xc, y0, front, depth), 0.05)
    return Footprint(floor.y if floor else None, round(width, 3), round(height, 3))


def piece_size(
    dims: Dims, aspect: float | None, fp: Footprint | None, room: Room
) -> Vec3:
    """Kind default x sheet aspect (w/h) x plate footprint, bounded by the kind + room."""
    w0, d0, h0 = dims
    base = w0 / h0
    sheet = _clamp(aspect, base / ASPECT_SPAN, base * ASPECT_SPAN) if aspect else base
    r = math.sqrt(base * sheet)  # geometric blend of the type ratio and the sheet ratio
    h = (fp.height_m + fp.width_m / r) / 2 if fp else h0
    h = min(_clamp(h, 0.5 * h0, 2.0 * h0), room.height)
    w = min(_clamp(r * h, 0.4 * w0, 2.5 * w0), room.width * 0.6)
    d = min(_clamp(d0 * h / h0, 0.5 * d0, 2.0 * d0), room.depth * 0.5)
    return Vec3(x=round(w, 3), y=round(d, 3), z=round(h, 3))


def shape_for(
    cls: Classified,
    description: str,
    aspect: float | None,
    fp: Footprint | None,
    room: Room,
) -> Shaped:
    size = piece_size(cls.dims, aspect, fp, room)
    return Shaped(
        kind=cls.kind,
        shape="cylinder" if cls.kind == "cylinder" else "box",
        size=size,
        params=kind_params(cls.kind, description, size.z),
    )


def prop_shape(obj: ObjectInput, aspect: float | None, room: Room) -> Shaped:
    """A movable prop: typed from name/description, sized by default x sheet aspect."""
    return shape_for(
        classify(obj.name, obj.description), obj.description, aspect, None, room
    )

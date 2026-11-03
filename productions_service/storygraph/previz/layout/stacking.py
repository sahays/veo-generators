"""Stacked set pieces (pure): a piece drawn standing ON another piece in the plate.

A set piece whose image box bottom lands inside the upper part of a larger piece's box,
with its centre column over that piece (a toolbox on a workbench), is not on the floor:
casting its box bottom onto the floor would push it far back and inflate it. It is placed
on top of its supporter instead: same depth as the supporter, `position.z` = the
supporter's top, width measured at the supporter's front plane, height = box top minus
the supporter's top, x kept within the supporter's footprint. Supporter = the smallest
qualifying box (deterministic tie-break by entity id). O(n^2) in pieces (tens).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ...keyframes.plan.models import ObjectInput
from ...schemas.previz_scene import Room, SetPiece, Vec3
from ..blocking.project import MasterCamera, world_x
from .kinds import Classified
from .proportions import BBox, Footprint, measure, shape_for

UPPER: Final[float] = 0.75  # bottom must sit in the upper 75 % of the supporter's box


def _area(b: BBox) -> float:
    return (b[2] - b[0]) * (b[3] - b[1])


def supporter_of(eid: str, boxes: Mapping[str, BBox]) -> str | None:
    """Id of the piece `eid` stands on (None: it stands on the floor)."""
    box = boxes[eid]
    cx = (box[0] + box[2]) / 2
    found: list[tuple[float, str]] = []
    for oid, o in boxes.items():
        if oid == eid or _area(o) <= _area(box):
            continue
        if o[0] <= cx <= o[2] and o[1] <= box[3] <= o[1] + UPPER * (o[3] - o[1]):
            found.append((_area(o), oid))
    return min(found)[1] if found else None


def stacked_piece(
    cam: MasterCamera,
    room: Room,
    item: tuple[ObjectInput, Classified, BBox, float | None],
    sup: SetPiece,
    color: str,
) -> SetPiece:
    """`item` = (object, its typing, its image box, its sheet aspect) on top of `sup`."""
    o, cls, box, aspect = item
    front = sup.position.y - sup.size.y / 2
    raw = measure(cam, box, front, cls.dims[1], on_floor=False)
    fp = Footprint(None, raw.width_m, max(raw.height_m - sup.size.z, 0.05))
    shaped = shape_for(cls, o.description, aspect, fp, room)
    size = shaped.size
    x = world_x(cam, (box[0] + box[2]) / 2, sup.position.y, sup.size.z + size.z / 2)
    half = max(sup.size.x / 2 - size.x / 2, 0.0)
    x = min(max(x, sup.position.x - half), sup.position.x + half)
    return SetPiece(
        entity_id=o.entity_id, name=o.name, shape=shaped.shape, kind=shaped.kind,
        params=shaped.params, size=size, color=color,
        position=Vec3(x=round(x, 3), y=sup.position.y, z=round(sup.size.z, 3)),
    )  # fmt: skip

"""Blocking stage context: the layout seen through the scene's plate (pure).

`Stage` bundles what every per-second rule needs: the master camera (calibrated when the
camera stage supplied one, else synthetic), the remap from this scene's plate x to the
layout's plate x (identity when the layout came from this plate), the stage line (the
depth characters walk on: just in front of the nearest floor-standing set piece; doors and
windows on the walls never count) and set-piece lookups by id / name, plus each movable
prop's typed shape (kind, size, params). `support_piece` resolves a prop's `"on the
<name>"` placement; `approach_y` is where an actor stands to work at a target.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from ...keyframes.plan.models import Keyframe, PlanInput
from ...schemas.previz_scene import CameraRig, LocationLayout, SetPiece, Vec3
from ..layout.kinds import classify
from ..layout.proportions import Shaped, prop_shape, shape_for
from .project import Aspect, MasterCamera, XRemap, floor_start, master_camera, to_image
from .project import world_x as _world_x

LINE_MARGIN: Final[float] = 0.6
FRONT_GAP: Final[float] = 0.35
WALL_PAD: Final[float] = 0.3
WALL_KINDS: Final[frozenset[str]] = frozenset({"door", "window"})
_ON_RE = re.compile(r"^on the (.+?)(?:,|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Stage:
    layout: LocationLayout
    cam: MasterCamera
    remap: XRemap
    line_y: float
    near_y: float
    pieces: dict[str, SetPiece]
    by_name: dict[str, SetPiece]
    shapes: dict[str, Shaped] = field(default_factory=dict)

    def world_x(self, x_img: float, y: float, z: float) -> float:
        """World X of this scene's plate x (remapped), clamped inside the side walls."""
        half = self.layout.room.width / 2 - WALL_PAD
        return min(max(_world_x(self.cam, self.remap(x_img), y, z), -half), half)

    def clamp_y(self, y: float) -> float:
        return round(min(max(y, self.near_y), self.layout.room.depth - WALL_PAD), 3)

    def prop_shape(self, oid: str, name: str) -> Shaped:
        """Typed shape of a movable prop (name-only typing for objects not in the clip)."""
        hit = self.shapes.get(oid)
        if hit is not None:
            return hit
        return shape_for(classify(name), "", None, None, self.layout.room)

    def support_piece(self, placement: str) -> SetPiece | None:
        m = _ON_RE.match(placement.strip())
        return self.by_name.get(m.group(1).strip().lower()) if m else None

    def anchor_piece(self, frame: Keyframe, entity_id: str) -> SetPiece | None:
        """The set piece an entity is (a set piece itself, or a prop standing on one)."""
        if entity_id in self.pieces:
            return self.pieces[entity_id]
        obj = next((o for o in frame.objects if o.entity_id == entity_id), None)
        return self.support_piece(obj.placement) if obj and not obj.holder_id else None

    def approach_y(self, frame: Keyframe, target_id: str) -> float | None:
        """Depth in front of the target's set piece; None when it stands on none."""
        piece = self.anchor_piece(frame, target_id)
        if piece is None:
            return None
        return self.clamp_y(piece.position.y - piece.size.y / 2 - FRONT_GAP)


def _remap(inp: PlanInput, layout: LocationLayout, cam: MasterCamera) -> XRemap:
    pairs: dict[str, tuple[float, float]] = {}
    for p in layout.set_pieces:
        if p.entity_id in inp.layout:
            centre = Vec3(x=p.position.x, y=p.position.y, z=p.size.z / 2)
            pairs[p.entity_id] = (inp.layout[p.entity_id], to_image(cam, centre)[0])
    return XRemap(pairs)


def _prop_shapes(
    inp: PlanInput, layout: LocationLayout, aspects: Mapping[str, float]
) -> dict[str, Shaped]:
    ids = {p.entity_id for p in layout.set_pieces}
    return {
        o.entity_id: prop_shape(o, aspects.get(o.entity_id), layout.room)
        for o in inp.objects
        if o.entity_id not in ids
    }


def build_stage(
    inp: PlanInput,
    layout: LocationLayout,
    aspect: Aspect,
    master: CameraRig | None = None,
    aspects: Mapping[str, float] | None = None,
) -> Stage:
    room = layout.room
    cam = master_camera(room, aspect, master)
    near = floor_start(cam, room) + WALL_PAD
    floor = [p for p in layout.set_pieces if p.kind not in WALL_KINDS]
    fronts = [p.position.y - p.size.y / 2 for p in floor]
    line = min(fronts) - LINE_MARGIN if fronts else room.depth * 0.5
    return Stage(
        layout=layout,
        cam=cam,
        remap=_remap(inp, layout, cam),
        line_y=min(max(line, near), room.depth - WALL_PAD),
        near_y=near,
        pieces={p.entity_id: p for p in layout.set_pieces},
        by_name={p.name.lower(): p for p in layout.set_pieces},
        shapes=_prop_shapes(inp, layout, aspects or {}),
    )

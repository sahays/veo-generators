"""Locked scene plate: which objects are set pieces, the plate spec and its cache key (pure).

A set piece is an object that, across every second of every clip in the scene, is alive in
the room, never held, never acted on by a beat and never changes placement — furniture and
fixtures. Set pieces are drawn ONCE into the empty-set master plate; every other object is a
dynamic prop drawn per keyframe. The plate key hashes everything that determines the plate,
so an unchanged scene reuses its plate (and therefore its camera and layout) forever.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from pydantic import BaseModel, Field

from ..plan.models import KeyframePlan, ObjectInput, PlanInput


class PlateSpec(BaseModel):
    scene_id: str
    location_name: str
    location_description: str = ""
    location_ref_uri: str | None = None
    style: str = ""
    time_of_day: str = ""
    set_pieces: list[ObjectInput] = Field(default_factory=list)

    @property
    def key(self) -> str:
        body = self.model_dump_json()
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _placements(plan: KeyframePlan) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for frame in plan.keyframes:
        for obj in frame.objects:
            out.setdefault(obj.entity_id, set()).add(
                "HELD" if obj.holder_id or not obj.visible else obj.placement
            )
    return out


def set_piece_ids(pairs: Sequence[tuple[PlanInput, KeyframePlan]]) -> list[str]:
    """Objects with exactly one visible, unheld placement in every clip, never a beat target."""
    targets = {b.target_id for inp, _ in pairs for b in inp.beats if b.target_id}
    seen: dict[str, set[str]] = {}
    present_in_all: set[str] | None = None
    for _, plan in pairs:
        placements = _placements(plan)
        present_in_all = (
            set(placements)
            if present_in_all is None
            else present_in_all & set(placements)
        )
        for oid, values in placements.items():
            seen.setdefault(oid, set()).update(values)
    keep = present_in_all or set()
    return sorted(
        oid
        for oid in keep
        if oid not in targets and len(seen[oid]) == 1 and "HELD" not in seen[oid]
    )


def plate_spec(pairs: Sequence[tuple[PlanInput, KeyframePlan]]) -> PlateSpec:
    """The scene's plate spec from its clips (first clip supplies location/style)."""
    inp = pairs[0][0]
    ids = set(set_piece_ids(pairs))
    return PlateSpec(
        scene_id=inp.scene_id,
        location_name=inp.location_name,
        location_description=inp.location_description,
        location_ref_uri=inp.location_ref_uri,
        style=inp.style,
        time_of_day=inp.time_of_day,
        set_pieces=[o for o in inp.objects if o.entity_id in ids],
    )

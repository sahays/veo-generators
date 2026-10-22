"""Object permanence back-fill for clip snapshots (pure).

The State Engine only records an object's location once an Event first mentions it, so a
set piece that has stood in the room all along (the wooden chest under the workbench) has no
`location` fact before that Event. Rendering that literally makes the object pop into
existence mid-clip, which video models answer with duplicates or vanishing props.

Rule: if an object is first *established* in the clip's location at snapshot `k` — it had no
location at all before, and nobody carries it in (not held at `k`) — it has been there from
the clip's first snapshot. Objects that are carried in, moved from elsewhere or created
(`alive_present`) keep their graph timing.
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import StateSnapshot


def _held_ids(snap: StateSnapshot) -> set[str]:
    return {st["holding"] for st in snap.states.values() if st.get("holding")}


def _first_established(
    snapshots: Sequence[StateSnapshot], object_id: str, location_id: str
) -> int | None:
    """Index where `object_id` is first established in `location_id` (None = not applicable)."""
    for idx, snap in enumerate(snapshots):
        st = snap.states.get(object_id, {})
        if not st.get("location"):
            continue
        if st["location"] != location_id or st.get("alive_present"):
            return None
        return idx if idx and object_id not in _held_ids(snap) else None
    return None


def backfill_established(
    snapshots: Sequence[StateSnapshot], object_ids: Sequence[str], location_id: str
) -> list[StateSnapshot]:
    """Copy of `snapshots` with established set pieces present from snapshot 0."""
    out = [s.model_copy(deep=True) for s in snapshots]
    for oid in object_ids:
        first = _first_established(out, oid, location_id)
        if first is None:
            continue
        static = {
            k: v
            for k, v in out[first].states[oid].items()
            if k in ("location", "supported_by")
        }
        for snap in out[:first]:
            snap.states[oid] = {**static, **snap.states.get(oid, {})}
    return out

"""Object state read from a graph `StateSnapshot` (pure): who holds what, which objects are
alive in the room, where they are placed and whether they can be seen.

Shared by the planner (per-keyframe objects) and event extraction (what changed between two
snapshots), so both derive presence / holder / visibility with exactly the same rules.
"""

from __future__ import annotations

from .models import BeatSpan, ObjectKey, PlanInput, StateSnapshot

_HIDDEN_PLACE = ("inside", "hidden", "concealed", "buried")
_CONTAINED = ("drawer", "box", "chest", "bag", "pocket", "under the lid")
_HIDDEN_HOLD = (
    "behind back",
    "behind his back",
    "behind her back",
    "hidden",
    "concealed",
)
_ABSENT = frozenset({"false", "no", "0", "absent", "gone", "destroyed", "consumed"})
_TIGHT = frozenset({"ECU", "CU", "MCU"})


def names_of(inp: PlanInput) -> dict[str, str]:
    """`entity id -> display name` for the location, cast and objects of the clip."""
    out = {inp.location_id: inp.location_name}
    out.update({c.entity_id: c.name for c in inp.cast})
    out.update({o.entity_id: o.name for o in inp.objects})
    return out


def holders_of(snap: StateSnapshot) -> dict[str, str]:
    """`object id -> holder id` from every `holding` fact in the snapshot."""
    return {st["holding"]: eid for eid, st in snap.states.items() if st.get("holding")}


def _alive(inp: PlanInput, st: dict[str, str], held: bool) -> bool:
    if (st.get("alive_present") or "").lower() in _ABSENT:
        return False
    return held or st.get("location") == inp.location_id


def _placement(st: dict[str, str], holder: str | None, names: dict[str, str]) -> str:
    if holder:
        return f"held by {names.get(holder, holder)}"
    parts: list[str] = []
    support = st.get("supported_by")
    if support:
        parts.append(f"on the {names.get(support, support)}")
    if st.get("sub_location"):
        parts.append(st["sub_location"])
    return ", ".join(parts) or "in its place in the room"


def _visible(st: dict[str, str], holder_state: dict[str, str] | None) -> bool:
    """Hidden when its holder conceals it, or it is contained in another object."""
    if holder_state is not None:
        where = (holder_state.get("sub_location") or "").lower()
        return not any(k in where for k in _HIDDEN_HOLD)
    where = (st.get("sub_location") or "").lower()
    contained = bool(st.get("supported_by")) and any(k in where for k in _CONTAINED)
    return not contained and not any(k in where for k in _HIDDEN_PLACE)


def exposed_ids(inp: PlanInput, beat: BeatSpan | None) -> frozenset[str]:
    """Objects the active beat acts on or names: they are visible while it plays."""
    if beat is None:
        return frozenset()
    text = f"{beat.action} {beat.pre_state} {beat.post_state}".lower()
    named = {o.entity_id for o in inp.objects if o.name.lower() in text}
    return frozenset(named | ({beat.target_id} if beat.target_id else set()))


def objects_at(
    inp: PlanInput, snap: StateSnapshot, exposed: frozenset[str] = frozenset()
) -> list[ObjectKey]:
    """Objects alive at `snap` (keyed by entity id, so each appears exactly once)."""
    names, holders = names_of(inp), holders_of(snap)
    cast_ids = {c.entity_id for c in inp.cast}
    tight = inp.camera.shot_size in _TIGHT
    out: list[ObjectKey] = []
    for obj in inp.objects:
        st = snap.states.get(obj.entity_id, {})
        holder = holders.get(obj.entity_id)
        if not _alive(inp, st, holder is not None):
            continue
        holder_state = snap.states.get(holder, {}) if holder else None
        out.append(
            ObjectKey(
                entity_id=obj.entity_id,
                name=obj.name,
                placement=_placement(st, holder, names),
                holder_id=holder,
                visible=obj.entity_id in exposed or _visible(st, holder_state),
                in_frame=not tight or obj.focus or holder in cast_ids,
                x=None if holder else inp.layout.get(obj.entity_id),
            )
        )
    return out

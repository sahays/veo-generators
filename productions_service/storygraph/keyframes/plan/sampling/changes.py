"""What visibly changes between two graph snapshots (pure): hand-overs, pick-ups and
put-downs (holder changes), entrances and exits, open/close and on/off states, objects
revealed or hidden, and other placement changes — each with a short human label.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..models import EventKind, ObjectKey, PlanInput, StateSnapshot
from ..state import holders_of, names_of, objects_at
from .models import KIND_RANK

_OPEN_WORDS: Final[frozenset[str]] = frozenset(
    {"open", "opened", "closed", "shut", "ajar", "locked", "unlocked"}
)
_POWER_VALUES: Final[frozenset[str]] = frozenset(
    {
        "on",
        "off",
        "switched on",
        "switched off",
        "powered on",
        "powered off",
        "lit",
        "unlit",
    }
)
_TOGGLE_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "open",
        "opened",
        "closed",
        "locked",
        "door",
        "door_state",
        "state",
        "power",
        "lit",
    }
)
_PLACE_ATTRS: Final[tuple[str, ...]] = ("sub_location", "supported_by")


@dataclass(frozen=True)
class Change:
    kind: EventKind
    label: str

    @property
    def rank(self) -> int:
        return KIND_RANK[self.kind]


def the(name: str) -> str:
    """Object noun phrase: "brass key" -> "the brass key" (no double article)."""
    low = name.lower()
    return name if low.startswith(("the ", "a ", "an ")) else f"the {name}"


def _holder_changes(
    before: StateSnapshot, after: StateSnapshot, names: dict[str, str]
) -> list[Change]:
    h0, h1 = holders_of(before), holders_of(after)
    out: list[Change] = []
    for oid in sorted(set(h0) | set(h1)):
        was, now = h0.get(oid), h1.get(oid)
        obj = the(names.get(oid, oid))
        if was == now:
            continue
        if was and now:
            label = f"{names.get(was, was)} hands {obj} to {names.get(now, now)}"
            out.append(Change("hand_over", label))
        elif now:
            out.append(Change("pick_up", f"{names.get(now, now)} picks up {obj}"))
        elif was:
            out.append(Change("put_down", f"{names.get(was, was)} puts down {obj}"))
    return out


def _cast_moves(
    inp: PlanInput, before: StateSnapshot, after: StateSnapshot
) -> list[Change]:
    room = inp.location_id
    out: list[Change] = []
    for c in inp.cast:
        was = before.states.get(c.entity_id, {}).get("location")
        now = after.states.get(c.entity_id, {}).get("location")
        if now == room and was not in (None, room):
            out.append(Change("entrance", f"{c.name} enters"))
        elif was == room and now not in (None, room):
            out.append(Change("exit", f"{c.name} leaves"))
    return out


def _toggle_kind(attr: str, value: str) -> EventKind | None:
    """open_close / on_off from whole words of the new value (never "on the table")."""
    low = value.lower().strip()
    if _OPEN_WORDS & set(low.replace(",", " ").split()):
        return "open_close"
    if low in _POWER_VALUES or attr in ("power", "lit"):
        return "on_off"
    return "open_close" if attr in _TOGGLE_ATTRS else None


def _state_change(name: str, attr: str, value: str) -> Change | None:
    """Open/close, on/off or placement change of one attribute of one entity."""
    kind = _toggle_kind(attr, value)
    if kind is not None and (attr in _TOGGLE_ATTRS or attr == "sub_location"):
        return Change(
            kind, f"{the(name)} is {value}" if value else f"{the(name)} changes"
        )
    if attr in _PLACE_ATTRS and value:
        return Change("location", f"{the(name)} is now {value}")
    return None


def _value(attr: str, st: dict[str, str], names: dict[str, str]) -> str:
    """Readable new value; a support id becomes "on the <name>"."""
    raw = st.get(attr, "")
    return f"on {the(names.get(raw, raw))}" if attr == "supported_by" and raw else raw


def _attribute_changes(
    inp: PlanInput, before: StateSnapshot, after: StateSnapshot, skip: set[str]
) -> dict[str, Change]:
    """`object id -> its first toggle/placement change` (objects in `skip` excluded)."""
    names = names_of(inp)
    out: dict[str, Change] = {}
    for obj in inp.objects:
        if obj.entity_id in skip:
            continue
        st0 = before.states.get(obj.entity_id, {})
        st1 = after.states.get(obj.entity_id, {})
        for attr in sorted(_TOGGLE_ATTRS | set(_PLACE_ATTRS)):
            change = (
                _state_change(obj.name, attr, _value(attr, st1, names))
                if st0.get(attr) != st1.get(attr)
                else None
            )
            if change is not None:
                out[obj.entity_id] = change
                break  # one change per object per transition
    return out


def _visibility_changes(
    inp: PlanInput, before: StateSnapshot, after: StateSnapshot, skip: set[str]
) -> list[Change]:
    def shown(snap: StateSnapshot) -> dict[str, ObjectKey]:
        return {o.entity_id: o for o in objects_at(inp, snap) if o.visible}

    was, now = shown(before), shown(after)
    out = [
        Change("reveal", f"{the(o.name)} is revealed")
        for oid, o in now.items()
        if oid not in was and oid not in skip
    ]
    return out + [
        Change("hide", f"{the(o.name)} is hidden")
        for oid, o in was.items()
        if oid not in now and oid not in skip
    ]


def snapshot_changes(
    inp: PlanInput, before: StateSnapshot, after: StateSnapshot
) -> list[Change]:
    """Every visible change from `before` to `after`, most significant first."""
    h0, h1 = holders_of(before), holders_of(after)
    moved = {oid for oid in set(h0) | set(h1) if h0.get(oid) != h1.get(oid)}
    toggled = _attribute_changes(inp, before, after, moved)
    changes = [
        *_holder_changes(before, after, names_of(inp)),
        *_cast_moves(inp, before, after),
        *toggled.values(),
        *_visibility_changes(inp, before, after, moved | set(toggled)),
    ]
    return sorted(changes, key=lambda c: c.rank)

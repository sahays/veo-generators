"""Data-driven per-clip object specs (only the clip's alive-and-relevant props).

`start` is the prop's own state before the clip's first Event (held_by / own resting
place / absent when created during the clip); `end` (for props the clip changes or
manipulates) is its state after the clip's last Event. Free-text placement is a last
resort and only taken from clauses whose subject is the prop itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..clips.models import ClipScript
from ..schema import InteractionStep
from ..timeline.handling import moved_props
from ..timeline.lifecycle import name_pattern
from ..views import ShotView
from .spec import ObjectSpec, ObjectState
from .symbols import ImageBindings, Symbols
from .text import IdResolver, clean, condense_identity

ABSENT_AT_START: Final[str] = "absent at the start; appears during the action"
CONSUMED: Final[str] = "consumed during the action; gone by the end"
_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(
    r";|(?<=[.!?])\s+|,\s+(?:while|and)\s+"
)
_SUBJECT_WINDOW: Final[int] = 4
_PREPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "on", "in", "at", "under", "beside", "against", "inside", "near", "by", "atop",
        "above", "below", "behind", "next", "upon", "hanging", "leaning", "resting",
        "lying",
    }
)  # fmt: skip


@dataclass(frozen=True)
class _PropFacts:
    pid: str
    name: str
    pattern: re.Pattern[str]
    identity: str


def _subject_clause(text: str, pattern: re.Pattern[str], resolver: IdResolver) -> str:
    """First clause of `text` whose subject (first few words) is the prop ('' if none)."""
    for raw in _CLAUSE_SPLIT_RE.split(clean(text, resolver)):
        clause = raw.strip().rstrip(".")
        head = " ".join(clause.split()[:_SUBJECT_WINDOW])
        if clause and pattern.search(head):
            return clause
    return ""


def _where_phrase(raw: str, own_name: str, loc_name: str) -> str:
    if not raw or raw.lower() in (own_name.lower(), loc_name.lower()):
        return ""
    first = raw.split(" ", 1)[0].lower()
    if first in _PREPOSITIONS or first.endswith("ing"):
        return raw
    return f"on the {raw}" if len(raw.split()) <= 3 else raw


def _state(
    view: ShotView, f: _PropFacts, sym: Symbols, edge: str, text: str
) -> ObjectState | None:
    """Object state at one clip edge (`edge` is '' for opening, 'end_' for closing)."""
    st = view.prop_states.get(f.pid, {})
    alive = st.get("alive_start" if not edge else "alive_end", "true") == "true"
    if not alive:
        return ObjectState(where=ABSENT_AT_START if not edge else CONSUMED)
    holder = sym.ref(st.get(f"{edge}held_by"))
    if holder:
        return ObjectState(held_by=holder)
    place = clean(st.get(f"{edge}supported_by"), sym.resolver)
    where = _where_phrase(place, f.name, view.location.canonical_name)
    orientation = clean(st.get(f"{edge}orientation"), sym.resolver)
    where = ", ".join(p for p in (orientation, where) if p)
    where = where or _subject_clause(text, f.pattern, sym.resolver)
    return ObjectState(where=where) if where else None


def _changes(st: dict[str, str]) -> bool:
    return any(
        st.get(k, "") != st.get(f"end_{k}", "")
        for k in ("supported_by", "orientation", "held_by")
    ) or (st.get("alive_start") != st.get("alive_end"))


def _facts(view: ShotView, pid: str, sym: Symbols, n_sent: int) -> _PropFacts:
    ent = view.prop_entities.get(pid)
    name = ent.canonical_name if ent else sym.name(pid)
    app = view.prop_appearances.get(pid)
    identity = condense_identity(
        app.visual_description if app else "", sym.resolver, [], max(1, n_sent)
    )
    return _PropFacts(pid, name, name_pattern(name), identity)


def build_objects(
    view: ShotView,
    clip: ClipScript,
    steps: list[InteractionStep],
    sym: Symbols,
    bindings: ImageBindings,
    identity_sentences: int,
) -> list[ObjectSpec]:
    """Typed object specs for the clip's props: start/end from the graph's clip window."""
    handled = moved_props(steps)
    out: list[ObjectSpec] = []
    for pid in dict.fromkeys(view.shot.prop_ids):
        f = _facts(view, pid, sym, identity_sentences)
        moves = pid in handled or _changes(view.prop_states.get(pid, {}))
        start = _state(view, f, sym, "", clip.opening_state) or ObjectState(
            where="in_place"
        )
        end = _state(view, f, sym, "end_", clip.closing_state) if moves else None
        out.append(
            ObjectSpec(
                id=sym.ids[pid],
                name=f.name,
                ref_image=bindings.ref_by_entity.get(pid),
                identity=f.identity or None,
                start=start,
                end=end if end != start else None,
                moves=moves,
            )
        )
    return out

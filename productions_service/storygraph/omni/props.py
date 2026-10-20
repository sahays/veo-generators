"""Data-driven per-clip object specs (only the clip's alive-and-relevant props).

`start` is the prop's state before the clip's first Event and `end` (for props the clip
changes or manipulates) its state after the clip's last Event, both in plain words from
graph facts: the holder, else its own location (`where`), plus state words (`condition`).
A prop consumed by the clip ends 'eaten by <name>' (else `CONSUMED`). Free text is a last
resort, taken only from clauses whose subject is the prop itself; the prop's room is the
final fallback, so no placeholder reaches the spec. `in_frame` is False for set dressing
the shot size excludes (`FramingPolicy.set_dressing_min_size`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..clips.limits import FRAMING, size_rank
from ..clips.models import ClipScript
from ..schema import InteractionStep
from ..timeline.handling import moved_props
from ..timeline.lifecycle import name_pattern
from ..timeline.placement import cut_phrase, surface_phrase
from ..views import ShotView
from .spec import ObjectSpec, ObjectState
from .symbols import ImageBindings, Symbols
from .text import IdResolver, clean, collapse_repeats, condense_identity

ABSENT_AT_START: Final[str] = "absent at the start; appears during the action"
CONSUMED: Final[str] = "consumed during the action; gone by the end"
EATEN_BY: Final[str] = "eaten by"
_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(
    r";|(?<=[.!?])\s+|,\s+(?:while|and)\s+"
)
_SUBJECT_WINDOW: Final[int] = 4
_MAX_WHERE_CHARS: Final[int] = 90
_CHANGE_KEYS: Final[tuple[str, ...]] = ("supported_by", "condition", "held_by")


def located_in(room: str) -> str:
    """Room-level fallback location ('in the Kitchen'); the linter treats it as loose."""
    return f"in the {room}"


@dataclass(frozen=True)
class _PropFacts:
    pid: str
    name: str
    pattern: re.Pattern[str]
    identity: str


@dataclass(frozen=True)
class _Framing:
    """Clip-wide inputs for `in_frame`: handled props, step/focus targets, wide-enough size."""

    handled: frozenset[str]
    targets: frozenset[str]
    wide: bool


def _subject_clause(text: str, pattern: re.Pattern[str], resolver: IdResolver) -> str:
    """First clause of `text` whose subject (first few words) is the prop ('' if none)."""
    for raw in _CLAUSE_SPLIT_RE.split(clean(text, resolver)):
        clause = raw.strip().rstrip(".")
        head = " ".join(clause.split()[:_SUBJECT_WINDOW])
        if clause and pattern.search(head):
            return cut_phrase(clause, _MAX_WHERE_CHARS)
    return ""


def _where(
    view: ShotView,
    f: _PropFacts,
    sym: Symbols,
    st: dict[str, str],
    edge: str,
    text: str,
) -> str:
    """Own location from facts, else a prop-subject clause, else the prop's room."""
    raw = clean(st.get(f"{edge}supported_by"), sym.resolver)
    own = raw.lower() not in (f.name.lower(), view.location.canonical_name.lower())
    place = (surface_phrase(raw) if own else "") or _subject_clause(
        text, f.pattern, sym.resolver
    )
    loc = st.get(f"{edge}location", "")
    room = sym.name(loc) if loc else view.location.canonical_name
    return collapse_repeats(place) or located_in(room)


def _state(
    view: ShotView, f: _PropFacts, sym: Symbols, edge: str, text: str
) -> ObjectState:
    """Object state at one clip edge (`edge` is '' for opening, 'end_' for closing)."""
    st = view.prop_states.get(f.pid, {})
    if st.get("alive_end" if edge else "alive_start", "true") != "true":
        eater = st.get("consumed_by", "")
        gone = f"{EATEN_BY} {eater}" if eater else CONSUMED
        return ObjectState(where=gone if edge else ABSENT_AT_START)
    cond = collapse_repeats(clean(st.get(f"{edge}condition"), sym.resolver)) or None
    holder = sym.ref(st.get(f"{edge}held_by"))
    if holder:
        return ObjectState(held_by=holder, condition=cond)
    return ObjectState(where=_where(view, f, sym, st, edge, text), condition=cond)


def _changes(st: dict[str, str]) -> bool:
    return any(st.get(k, "") != st.get(f"end_{k}", "") for k in _CHANGE_KEYS) or (
        st.get("alive_start") != st.get("alive_end")
    )


def _facts(view: ShotView, pid: str, sym: Symbols, n_sent: int) -> _PropFacts:
    ent = view.prop_entities.get(pid)
    name = ent.canonical_name if ent else sym.name(pid)
    app = view.prop_appearances.get(pid)
    identity = condense_identity(
        app.visual_description if app else "", sym.resolver, [], max(1, n_sent)
    )
    return _PropFacts(pid, name, name_pattern(name), identity)


def _framing(view: ShotView, steps: list[InteractionStep]) -> _Framing:
    cam = view.shot.camera
    targets = {s.target_id for s in steps if s.target_id} | {cam.focus_target_id or ""}
    wide = size_rank(cam.shot_size) >= size_rank(FRAMING.set_dressing_min_size)
    return _Framing(frozenset(moved_props(steps)), frozenset(targets), wide)


def _object(
    view: ShotView,
    clip: ClipScript,
    f: _PropFacts,
    sym: Symbols,
    bindings: ImageBindings,
    fr: _Framing,
) -> ObjectSpec:
    moves = f.pid in fr.handled or _changes(view.prop_states.get(f.pid, {}))
    start = _state(view, f, sym, "", clip.opening_state)
    end = _state(view, f, sym, "end_", clip.closing_state) if moves else None
    held = bool(start.held_by or (end and end.held_by))
    return ObjectSpec(
        id=sym.ids[f.pid],
        name=f.name,
        ref_image=bindings.ref_by_entity.get(f.pid),
        identity=f.identity or None,
        start=start,
        end=end if end != start else None,
        moves=moves,
        in_frame=fr.wide or moves or held or f.pid in fr.targets,
    )


def build_objects(
    view: ShotView,
    clip: ClipScript,
    steps: list[InteractionStep],
    sym: Symbols,
    bindings: ImageBindings,
    identity_sentences: int,
) -> list[ObjectSpec]:
    """Typed object specs for the clip's props: start/end from the graph's clip window."""
    fr = _framing(view, steps)
    return [
        _object(
            view, clip, _facts(view, pid, sym, identity_sentences), sym, bindings, fr
        )
        for pid in dict.fromkeys(view.shot.prop_ids)
    ]

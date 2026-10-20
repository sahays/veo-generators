"""Data-driven per-shot object specs (only props in the shot).

A prop the clip moves (`moves=true`) gets `start`/`end` from the clip's own opening/closing
state, then its steps' pre/post states. A prop the clip does not touch gets its resting
place as `start` and `moves=false`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..clips.models import ClipScript
from ..schema import InteractionStep
from ..views import ShotView
from .spec import ObjectSpec, ObjectState
from .symbols import ImageBindings, Symbols
from .text import IdResolver, clean, condense_identity

_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r";|(?<=[.!?])\s+")
_PREPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "on",
        "in",
        "at",
        "under",
        "beside",
        "against",
        "inside",
        "near",
        "by",
        "atop",
        "above",
        "below",
        "behind",
        "next",
        "upon",
        "hanging",
        "leaning",
        "resting",
        "lying",
    }
)


@dataclass(frozen=True)
class _PropFacts:
    pid: str
    name: str
    pattern: re.Pattern[str]
    rest: ObjectState
    identity: str


def name_pattern(name: str) -> re.Pattern[str]:
    """Whole-word match on the full name or its head noun ('Strawberry Bowl' -> 'bowl')."""
    words = [w for w in re.findall(r"[\w'-]+", name) if w]
    alts = {re.escape(name.strip())} | ({re.escape(words[-1])} if words else set())
    return re.compile(
        r"\b(?:" + "|".join(sorted(alts, key=len, reverse=True)) + r")\b", re.IGNORECASE
    )


def _mention(text: str, pattern: re.Pattern[str], resolver: IdResolver) -> str:
    """Join the clauses of `text` that mention the prop ('' when none do)."""
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(clean(text, resolver))]
    return "; ".join(c.rstrip(".") for c in clauses if c and pattern.search(c))


def _where_phrase(raw: str, own_name: str, loc_name: str) -> str:
    if not raw or raw.lower() in (own_name.lower(), loc_name.lower()):
        return "in_place"
    first = raw.split(" ", 1)[0].lower()
    if first in _PREPOSITIONS or first.endswith("ing"):
        return raw
    return f"on the {raw}" if len(raw.split()) <= 3 else raw


def _facts(view: ShotView, pid: str, sym: Symbols, n_sent: int) -> _PropFacts:
    ent = view.prop_entities.get(pid)
    name = ent.canonical_name if ent else sym.name(pid)
    st = view.prop_states.get(pid, {})
    holder = sym.ref(st.get("held_by"))
    rest = (
        ObjectState(held_by=holder)
        if holder
        else ObjectState(
            where=_where_phrase(
                clean(st.get("supported_by"), sym.resolver),
                name,
                view.location.canonical_name,
            )
        )
    )
    app = view.prop_appearances.get(pid)
    identity = condense_identity(
        app.visual_description if app else "", sym.resolver, [], n_sent
    )
    return _PropFacts(pid, name, name_pattern(name), rest, identity)


def _state_pair(
    f: _PropFacts, clip: ClipScript, steps: list[InteractionStep], r: IdResolver
) -> tuple[ObjectState, ObjectState | None]:
    """(start, end) for a moved prop from the clip's own states, then its steps."""
    mine = [s for s in steps if s.target_id == f.pid]
    start = _mention(clip.opening_state, f.pattern, r) or (
        _mention(mine[0].pre_state, f.pattern, r) if mine else ""
    )
    end = _mention(clip.closing_state, f.pattern, r) or (
        _mention(mine[-1].post_state, f.pattern, r) if mine else ""
    )
    return (
        ObjectState(where=start) if start else f.rest,
        ObjectState(where=end) if end else None,
    )


def build_objects(
    view: ShotView,
    clip: ClipScript,
    steps: list[InteractionStep],
    sym: Symbols,
    bindings: ImageBindings,
    identity_sentences: int,
) -> list[ObjectSpec]:
    """Classify each shot prop as moved/static by this clip and emit typed object specs."""
    targeted = {s.target_id for s in steps if s.target_id}
    out: list[ObjectSpec] = []
    for pid in dict.fromkeys(view.shot.prop_ids):
        f = _facts(view, pid, sym, identity_sentences)
        moves = pid in targeted or bool(f.pattern.search(clip.omni_prompt))
        start, end = (
            _state_pair(f, clip, steps, sym.resolver) if moves else (f.rest, None)
        )
        out.append(
            ObjectSpec(
                id=sym.ids[pid],
                name=f.name,
                ref_image=bindings.ref_by_entity.get(pid),
                identity=f.identity or None,
                start=start,
                end=end,
                moves=moves,
            )
        )
    return out

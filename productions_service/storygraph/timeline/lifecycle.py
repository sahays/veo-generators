"""Object lifecycles and the per-clip prop set.

An object exists from its creation to its destruction/consumption:
- `alive_present` facts are authoritative (`true` creates, `false` destroys/consumes).
- Emergent objects (puddles, spills, stains, shards, smoke ...) without an explicit creation
  fact come into being at their first substantive evidence: a non-boilerplate state effect,
  being held, a clip step that targets it, or a mention in a clip's closing state.
- Every other object pre-exists the story.

The props of a clip are the objects that are alive during the clip window *and* relevant
to it (targeted or named by the clip, held or placed in frame by its own state, or changed by its
Events) — never the whole-scene closure.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from ..clips.models import ClipScript
from ..schema import Entity, Event, InteractionStep, StateFact
from .clip_events import ClipWindow
from .handling import head_noun

_BOILERPLATE_ATTRS: Final[frozenset[str]] = frozenset(
    {"location", "wearing", "mood", "injury", "alive_present"}
)
_EMERGENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:puddles?|spills?|splash(?:es)?|stains?|mess|crumbs|shards|fragments|pieces|"
    r"smoke|fire|flames?|holes?|cracks?|footprints?|debris|droplets)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Lifecycle:
    """Existence interval `[exists_from, exists_until)` in story orders (None = unbounded)."""

    entity_id: str
    exists_from: int | None = None
    exists_until: int | None = None

    def alive_at(self, order: int) -> bool:
        started = self.exists_from is None or order >= self.exists_from
        return started and (self.exists_until is None or order < self.exists_until)

    def alive_during(self, win: ClipWindow) -> bool:
        """True when the interval overlaps the clip (alive at open, close, or in between)."""
        started = self.exists_from is None or self.exists_from <= win.close_at
        return started and (
            self.exists_until is None or self.exists_until > win.open_at
        )


def name_pattern(name: str) -> re.Pattern[str]:
    """Whole-word match on the full name or its head noun ('Glass of Water' -> 'glass')."""
    head = head_noun(name)
    alts = {re.escape(name.strip())} | ({re.escape(head)} if head else set())
    body = "|".join(sorted(alts, key=len, reverse=True))
    return re.compile(rf"\b(?:{body})s?\b", re.IGNORECASE)


def _alive_bounds(facts: list[StateFact]) -> tuple[int | None, int | None]:
    born = [f.valid_from_order for f in facts if f.value.lower() == "true"]
    dead = [f.valid_from_order for f in facts if f.value.lower() == "false"]
    start = min(born) if born else None
    ends = [d for d in dead if start is None or d > start]
    return start, (min(ends) if ends else None)


def substantive_orders(events: Iterable[Event], entity_id: str) -> list[int]:
    """Orders of Events that change the object meaningfully (not boilerplate restatements)."""
    return [
        ev.story_order
        for ev in events
        for eff in ev.effects
        if (eff.entity_id == entity_id and eff.attribute not in _BOILERPLATE_ATTRS)
        or (eff.attribute == "holding" and eff.new_value == entity_id)
    ]


@dataclass(frozen=True)
class ClipEvidence:
    """Clip-level inputs for lifecycle evidence of emergent objects."""

    window: ClipWindow
    clip: ClipScript
    steps: tuple[InteractionStep, ...]


def _text_evidence(ent: Entity, clips: list[ClipEvidence]) -> list[int]:
    """Clip-edge orders where the emergent object is targeted or named (name or alias)."""
    pats = [name_pattern(n) for n in (ent.canonical_name, *ent.aliases) if n.strip()]

    def named(text: str) -> bool:
        return any(p.search(text) for p in pats)

    out: list[int] = []
    for c in clips:
        if any(s.target_id == ent.id for s in c.steps) or named(c.clip.closing_state):
            out.append(c.window.close_at)
        if named(c.clip.opening_state):
            out.append(c.window.open_at)
    return out


def object_lifecycle(
    ent: Entity, facts: list[StateFact], events: list[Event], clips: list[ClipEvidence]
) -> Lifecycle:
    """Lifecycle of one object from its own facts, events and clip evidence."""
    alive = [f for f in facts if f.attribute == "alive_present"]
    start, until = _alive_bounds(alive)
    if start is None and _EMERGENT_RE.search(ent.canonical_name):
        evidence = substantive_orders(events, ent.id) + _text_evidence(ent, clips)
        start = min(evidence) if evidence else None
    return Lifecycle(ent.id, start, until)


def _named(
    pat: re.Pattern[str], clip: ClipScript, steps: tuple[InteractionStep, ...]
) -> bool:
    texts = [clip.omni_prompt, clip.opening_state, clip.closing_state]
    texts += [s.action for s in steps]
    return any(pat.search(t) for t in texts if t)


def is_relevant(
    ent: Entity, ev: ClipEvidence, clip_events: list[Event], anchored: frozenset[str]
) -> bool:
    """Targeted/named by the clip, anchored (held or placed in frame), or changed by its Events."""
    if ent.id in anchored or any(s.target_id == ent.id for s in ev.steps):
        return True
    if substantive_orders(clip_events, ent.id):
        return True
    return _named(name_pattern(ent.canonical_name), ev.clip, ev.steps)


def clip_prop_ids(
    objects: list[Entity],
    lifecycles: dict[str, Lifecycle],
    ev: ClipEvidence,
    clip_events: list[Event],
    anchored: frozenset[str],
) -> list[str]:
    """Alive-and-relevant objects for one clip, targeted props first (step order)."""
    targeted = [s.target_id for s in ev.steps if s.target_id]
    rank = {pid: i for i, pid in enumerate(dict.fromkeys(targeted))}
    keep = [
        o.id
        for o in objects
        if lifecycles.get(o.id, Lifecycle(o.id)).alive_during(ev.window)
        and is_relevant(o, ev, clip_events, anchored)
    ]
    return sorted(keep, key=lambda pid: rank.get(pid, len(rank)))

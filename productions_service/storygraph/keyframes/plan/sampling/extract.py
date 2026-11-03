"""Candidate keyframe moments of one clip, extracted from the plan input (pure, no LLM).

* clip start (t=0) and clip end (t=duration): always;
* graph state changes: snapshot `i -> i+1` is shown from beat `i`'s midpoint (the planner's
  switch point), so its changes (`changes.snapshot_changes`) become one candidate there;
* contact: a beat's actor reaches a target whose position is known (layout / another
  character) at the beat's end;
* beat starts and ends.
Large-motion midpoints need the selected neighbours, so `select` adds them.
"""

from __future__ import annotations

from typing import Final

from ..models import BeatSpan, PlanInput
from ..state import names_of
from .changes import Change, snapshot_changes, the
from .models import BEAT, ENDPOINT, STATE, Candidate

MAX_LABEL_PARTS: Final[int] = 2


def combined(t: float, changes: list[Change]) -> Candidate:
    """One state candidate for simultaneous changes (most significant kind and first)."""
    parts = [c.label for c in changes[:MAX_LABEL_PARTS]]
    more = " …" if len(changes) > MAX_LABEL_PARTS else ""
    return Candidate(t, STATE, changes[0].kind, "; ".join(parts) + more)


def _state_candidates(inp: PlanInput) -> list[Candidate]:
    out: list[Candidate] = []
    pairs = zip(inp.snapshots, inp.snapshots[1:], strict=False)
    for beat, (before, after) in zip(inp.beats, pairs, strict=False):
        changes = snapshot_changes(inp, before, after)
        if changes:
            out.append(combined(round((beat.t_start + beat.t_end) / 2, 3), changes))
    return out


def _contact(inp: PlanInput, beat: BeatSpan, names: dict[str, str]) -> Candidate | None:
    cast = {c.entity_id for c in inp.cast}
    target = beat.target_id or ""
    known = target in inp.layout or target in cast
    if beat.actor_id not in cast or not known or target == beat.actor_id:
        return None
    who = names.get(beat.actor_id, beat.actor_id)
    what = names.get(target, target)
    noun = what if target in cast else the(what)
    return Candidate(beat.t_end, STATE, "contact", f"{who} reaches {noun}")


def _beat_candidates(inp: PlanInput, names: dict[str, str]) -> list[Candidate]:
    out: list[Candidate] = []
    for beat in inp.beats:
        action = beat.action.rstrip(".")
        out.append(Candidate(beat.t_start, BEAT, "beat_start", f"begins: {action}"))
        out.append(Candidate(beat.t_end, BEAT, "beat_end", f"done: {action}"))
        contact = _contact(inp, beat, names)
        out += [contact] if contact else []
    return out


def extract_candidates(inp: PlanInput) -> list[Candidate]:
    """Every candidate moment of the clip (unsorted, may overlap; `select` resolves)."""
    end = round(inp.duration_s, 3)
    names = names_of(inp)
    return [
        Candidate(0.0, ENDPOINT, "clip_start", "Clip start"),
        Candidate(end, ENDPOINT, "clip_end", "Clip end"),
        *_state_candidates(inp),
        *_beat_candidates(inp, names),
    ]

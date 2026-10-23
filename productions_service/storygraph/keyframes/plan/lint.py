"""Invariant lint for `KeyframePlan`s (per clip and across the clips of a scene).

* object_count / object_duplicate: the set of alive objects only changes at a second where
  the graph snapshot changed (a beat created/consumed/moved it into or out of the room), and
  no object is ever listed twice or with a count other than one;
* position_jump: a character's screen column moves at most one column per second;
* wardrobe_change: a character's wardrobe is constant across a clip and across a scene;
* timeline_open / timeline_close: second 0 equals the clip's opening graph state and the
  last second its closing state (objects alive and who holds what);
* scene_handoff: consecutive clips of a scene hand off the same objects, holders, positions.
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Sequence
from typing import Literal

from .models import (
    Keyframe,
    KeyframePlan,
    LintIssue,
    PlanInput,
    StateSnapshot,
)
from .motion import MAX_STEP_X
from .planner import objects_at

_StateKey = dict[str, str | None]
TimelineCode = Literal["timeline_open", "timeline_close"]


def _object_state(frame: Keyframe) -> _StateKey:
    """`object id -> holder id` (None = not held) for every object alive in `frame`."""
    return {o.entity_id: o.holder_id for o in frame.objects}


def _duplicates(plan: KeyframePlan, frame: Keyframe) -> list[LintIssue]:
    counts = Counter(o.entity_id for o in frame.objects)
    bad = {o.entity_id for o in frame.objects if o.count != 1} | {
        k for k, n in counts.items() if n > 1
    }
    return [
        LintIssue(
            code="object_duplicate",
            shot_id=plan.shot_id,
            t=frame.t,
            entity_id=oid,
            message=f"{oid} must appear exactly once at t={frame.t}",
        )
        for oid in sorted(bad)
    ]


def _count_changes(
    plan: KeyframePlan, prev: Keyframe, cur: Keyframe
) -> list[LintIssue]:
    changed = set(_object_state(prev)) ^ set(_object_state(cur))
    if not changed or prev.snapshot_index != cur.snapshot_index:
        return []
    return [
        LintIssue(
            code="object_count",
            shot_id=plan.shot_id,
            t=cur.t,
            entity_id=oid,
            message=f"{oid} appears/vanishes at t={cur.t} without a graph state change",
        )
        for oid in sorted(changed)
    ]


def _position_jumps(
    plan: KeyframePlan, prev: Keyframe, cur: Keyframe
) -> list[LintIssue]:
    before = {c.entity_id: c.x for c in prev.characters}
    return [
        LintIssue(
            code="position_jump",
            shot_id=plan.shot_id,
            t=cur.t,
            entity_id=c.entity_id,
            message=f"{c.name} moves {abs(c.x - before[c.entity_id]):.2f} frame widths at t={cur.t}",
        )
        for c in cur.characters
        if c.entity_id in before and abs(c.x - before[c.entity_id]) > MAX_STEP_X + 1e-6
    ]


def _wardrobe(plans: Sequence[KeyframePlan]) -> list[LintIssue]:
    first: dict[str, str] = {}
    out: list[LintIssue] = []
    for plan in plans:
        for frame in plan.keyframes:
            for c in frame.characters:
                seen = first.setdefault(c.entity_id, c.wardrobe)
                if seen != c.wardrobe:
                    out.append(
                        LintIssue(
                            code="wardrobe_change",
                            shot_id=plan.shot_id,
                            t=frame.t,
                            entity_id=c.entity_id,
                            message=f"{c.name} wardrobe changes to {c.wardrobe!r}",
                        )
                    )
    return out


def _timeline(plan: KeyframePlan, inp: PlanInput) -> list[LintIssue]:
    if not inp.snapshots or not plan.keyframes:
        return []
    checks: tuple[tuple[TimelineCode, Keyframe, StateSnapshot], ...] = (
        ("timeline_open", plan.keyframes[0], inp.snapshots[0]),
        ("timeline_close", plan.keyframes[-1], inp.snapshots[-1]),
    )
    out: list[LintIssue] = []
    for code, frame, snap in checks:
        want = {o.entity_id: o.holder_id for o in objects_at(inp, snap)}
        got = _object_state(frame)
        for oid in sorted(set(want) | set(got)):
            if want.get(oid, "∅") != got.get(oid, "∅"):
                out.append(
                    LintIssue(
                        code=code,
                        shot_id=plan.shot_id,
                        t=frame.t,
                        entity_id=oid,
                        message=f"{oid}: plan {got.get(oid, 'absent')} != graph {want.get(oid, 'absent')}",
                    )
                )
    return out


def lint_plan(plan: KeyframePlan, inp: PlanInput | None = None) -> list[LintIssue]:
    """All invariant violations of one clip plan (`inp` enables the timeline checks)."""
    out: list[LintIssue] = []
    frames = plan.keyframes
    for idx, frame in enumerate(frames):
        out += _duplicates(plan, frame)
        if idx:
            out += _count_changes(plan, frames[idx - 1], frame)
            out += _position_jumps(plan, frames[idx - 1], frame)
    out += _wardrobe([plan])
    return out + (_timeline(plan, inp) if inp is not None else [])


def _handoff(prev: KeyframePlan, cur: KeyframePlan) -> list[LintIssue]:
    end, start = prev.keyframes[-1], cur.keyframes[0]
    a, b = _object_state(end), _object_state(start)
    pos_a = {c.entity_id: round(c.x, 2) for c in end.characters}
    diffs = [
        oid for oid in sorted(set(a) | set(b)) if a.get(oid, "∅") != b.get(oid, "∅")
    ]
    diffs += [
        c.entity_id
        for c in start.characters
        if c.entity_id in pos_a and pos_a[c.entity_id] != round(c.x, 2)
    ]
    return [
        LintIssue(
            code="scene_handoff",
            shot_id=cur.shot_id,
            t=0,
            entity_id=eid,
            message=f"{eid} differs between end of {prev.shot_id} and start of {cur.shot_id}",
        )
        for eid in diffs
    ]


def lint_scene(plans: Sequence[KeyframePlan]) -> list[LintIssue]:
    """Cross-clip invariants for the ordered clip plans of one scene."""
    ordered = sorted(plans, key=lambda p: p.clip_index)
    out = _wardrobe(ordered)
    for prev, cur in itertools.pairwise(ordered):
        if prev.keyframes and cur.keyframes:
            out += _handoff(prev, cur)
    return out

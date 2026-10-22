"""Clip↔event mapping: which story Events each `ClipScript` plays, and its state window.

Interaction steps carry no event links, so steps are aligned to the scene's Events with a
monotone dynamic-programming alignment (O(steps × events)): every Event is assigned to
exactly one step, step order never goes backwards, and the score is token overlap between
step text and event summary plus an entity bonus (the step's target is changed by the
event) and a small diagonal prior that breaks ties for text-less data.

A clip plays the union of its steps' Events. Its window uses `state_at` (post-state)
semantics with integer story orders: `open_at = first_order - 1` is the state *before* the
clip's first Event and `close_at = last_order` is the state *after* its last Event. A clip
that plays no Event opens and closes on the previous clip's closing state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..clips.models import ClipScript
from ..schema import Event, InteractionStep, Scene

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")
_STOP: Final[frozenset[str]] = frozenset(
    {
        "the", "and", "his", "her", "its", "with", "from", "into", "onto", "over",
        "then", "while", "their", "toward", "towards", "that", "this", "for", "has",
        "him", "she", "they", "one", "out", "off", "back", "down", "away",
    }
)  # fmt: skip
_STEM_LEN: Final[int] = 5
_TARGET_BONUS: Final[float] = 0.3
_ACTOR_BONUS: Final[float] = 0.05
_PRIOR_WEIGHT: Final[float] = 0.1


@dataclass(frozen=True)
class ClipWindow:
    """Typed contract: the Events a clip plays and the orders of its opening/closing state."""

    clip_index: int
    event_ids: tuple[str, ...]
    open_at: int
    close_at: int

    @property
    def first_order(self) -> int:
        """Order of the clip's first Event (its opening order when it plays none).

        Used as `Shot.story_order`: sorts shots and dates scene-level facts (location,
        appearance) from the clip's first beat; per-entity opening state uses `open_at`.
        """
        return self.open_at + 1 if self.event_ids else self.open_at


def _tokens(text: str) -> frozenset[str]:
    words = _WORD_RE.findall(text.lower())
    return frozenset(w[:_STEM_LEN] for w in words if len(w) > 2 and w not in _STOP)


def _step_tokens(step: InteractionStep) -> frozenset[str]:
    return _tokens(f"{step.action} {step.detail} {step.post_state}")


def _changed_ids(ev: Event) -> frozenset[str]:
    """Entities an Event changes (effect subjects and held objects), not mere participants."""
    held = {e.new_value for e in ev.effects if e.attribute == "holding" and e.new_value}
    return frozenset({e.entity_id for e in ev.effects} | held)


def _similarity(step: InteractionStep, s_tok: frozenset[str], ev: Event) -> float:
    e_tok = _tokens(ev.summary)
    union = s_tok | e_tok
    score = len(s_tok & e_tok) / len(union) if union else 0.0
    if step.target_id and step.target_id in _changed_ids(ev):
        score += _TARGET_BONUS
    return score + (_ACTOR_BONUS if step.actor_id in ev.participants else 0.0)


def _score_matrix(
    steps: list[InteractionStep], events: list[Event]
) -> list[list[float]]:
    """score[j][i]: fit of event j to step i, including the diagonal prior."""
    n, m = len(steps), len(events)
    toks = [_step_tokens(s) for s in steps]
    return [
        [
            _similarity(steps[i], toks[i], events[j])
            - _PRIOR_WEIGHT * abs((j + 0.5) / m - (i + 0.5) / n)
            for i in range(n)
        ]
        for j in range(m)
    ]


def _forward(score: list[list[float]]) -> tuple[list[list[float]], list[list[int]]]:
    """best[j][i] = score[j][i] + max(best[j-1][0..i]); back holds that argmax."""
    n = len(score[0])
    best = [list(score[0])]
    back = [list(range(n))]
    for j in range(1, len(score)):
        run_val, run_arg = float("-inf"), 0
        row, arg_row = [0.0] * n, [0] * n
        for i in range(n):
            if best[j - 1][i] > run_val:
                run_val, run_arg = best[j - 1][i], i
            row[i], arg_row[i] = score[j][i] + run_val, run_arg
        best.append(row)
        back.append(arg_row)
    return best, back


def align_steps_to_events(
    steps: list[InteractionStep], events: list[Event]
) -> dict[int, list[str]]:
    """Monotone alignment: `step_index -> [event ids]` (every event lands on one step)."""
    if not steps or not events:
        return {}
    best, back = _forward(_score_matrix(steps, events))
    last = best[-1]
    i = max(range(len(last)), key=last.__getitem__)
    owner = [0] * len(events)
    for j in range(len(events) - 1, -1, -1):
        owner[j] = i
        i = back[j][i]
    out: dict[int, list[str]] = {}
    for j, ev in enumerate(events):
        out.setdefault(steps[owner[j]].step_index, []).append(ev.id)
    return out


def _prelude_len(steps: list[InteractionStep], events: list[Event]) -> int:
    """Leading establishing Events unrelated to every step (set-up state before clip 1):
    no text fit and no shared actor/target with any step."""
    toks = [_step_tokens(s) for s in steps]
    involved = {s.actor_id for s in steps} | {s.target_id for s in steps if s.target_id}

    def related(ev: Event) -> bool:
        if involved & (set(ev.participants) | _changed_ids(ev)):
            return True
        return any(
            _similarity(s, t, ev) > 0.0 for s, t in zip(steps, toks, strict=True)
        )

    return next((j for j, ev in enumerate(events) if related(ev)), len(events))


def _aligned(
    scene: Scene, events: list[Event]
) -> tuple[list[Event], int, dict[int, list[str]]]:
    """(ordered scene events, prelude length, `step_index -> [event ids]`)."""
    ordered = sorted(events, key=lambda e: (e.story_order, e.id))
    steps = sorted(scene.interaction_steps, key=lambda s: s.step_index)
    head = _prelude_len(steps, ordered) if steps else 0
    return ordered, head, align_steps_to_events(steps, ordered[head:])


def scene_step_events(scene: Scene, events: list[Event]) -> dict[int, list[str]]:
    """`step_index -> [event ids]` exactly as `scene_clip_windows` aligns them."""
    return _aligned(scene, events)[2]


def scene_clip_windows(scene: Scene, events: list[Event]) -> dict[int, ClipWindow]:
    """`clip_index -> ClipWindow` for every clip of `scene` (events are the scene's own)."""
    ordered, head, by_step = _aligned(scene, events)
    order_of = {e.id: e.story_order for e in ordered}
    if head:
        cursor = ordered[head - 1].story_order
    else:
        cursor = ordered[0].story_order - 1 if ordered else scene.index * 10 - 1
    out: dict[int, ClipWindow] = {}
    for clip in sorted(scene.clips, key=lambda c: c.clip_index):
        out[clip.clip_index] = _window(clip, by_step, order_of, cursor)
        cursor = out[clip.clip_index].close_at
    return out


def _window(
    clip: ClipScript,
    by_step: dict[int, list[str]],
    order_of: dict[str, int],
    cursor: int,
) -> ClipWindow:
    ids = [
        eid for si in dict.fromkeys(clip.step_indices) for eid in by_step.get(si, [])
    ]
    ids.sort(key=lambda eid: (order_of[eid], eid))
    if not ids:
        return ClipWindow(clip.clip_index, (), cursor, cursor)
    return ClipWindow(
        clip.clip_index, tuple(ids), order_of[ids[0]] - 1, order_of[ids[-1]]
    )

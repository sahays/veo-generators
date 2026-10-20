"""Deterministic clip edits for S7 lint remediation (pure: no repo access).

* `split_clip` — partition an overloaded clip's steps into contiguous clips within
  `CLIP_LIMITS`, each line of dialogue following the step it reacts to.
* `move_overflow_lines` — shift dialogue from an over-wordy clip to an adjacent clip.

Both return a `ClipEdit` whose `origin` maps every new `clip_index` to the old clip whose
shot (camera/look/cast) it inherits, or None for a brand-new clip that needs the director.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from .builder import chain_continuity, make_clip
from .limits import CLIP_LIMITS
from .models import ClipScript
from .partition import partition_steps
from .text import DialogueRef, StepRef

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z']+")
_STEM_LEN: Final[int] = 4


@dataclass(frozen=True)
class ClipEdit:
    """Result of one deterministic clip edit on a scene."""

    clips: list[ClipScript]
    origin: dict[int, int | None]
    note: str


def _verb_stem(step: StepRef) -> str:
    """Stem of the first word of the action that is not the actor's name."""
    name = {t.lower() for t in _TOKEN_RE.findall(step.actor_name)}
    words = [t.lower() for t in _TOKEN_RE.findall(step.action) if t.lower() not in name]
    return words[0][:_STEM_LEN] if words else ""


def line_step_position(prompt: str, line: DialogueRef, chunk: Sequence[StepRef]) -> int:
    """0-based position in `chunk` of the step `line` follows in `prompt`.

    Steps are located by their verb stem in prompt order; when the line or the verbs cannot be
    found, the line's relative position in the prompt decides.
    """
    at = prompt.find(line.text.strip()) if line.text.strip() else -1
    if at < 0 or not chunk:
        return max(0, len(chunk) - 1)
    lower = prompt.lower()
    first = _verb_stem(chunk[0])
    if not first or lower.find(first) < 0:
        return min(int(at / max(1, len(prompt)) * len(chunk)), len(chunk) - 1)
    cursor, done = 0, 0
    for step in chunk:
        stem = _verb_stem(step)
        hit = lower.find(stem, cursor) if stem else -1
        if hit < 0 or hit >= at:
            break
        cursor, done = hit + len(stem), done + 1
    return min(max(done - 1, 0), len(chunk) - 1)


def _reindex(
    before: list[ClipScript], at: int, parts: list[ClipScript]
) -> tuple[list[ClipScript], dict[int, int | None]]:
    """Replace clip `before[at]` by `parts` (first part keeps its shot), renumbering 1..N."""
    seq: list[tuple[ClipScript, int | None]] = [
        *((c, c.clip_index) for c in before[:at]),
        *((p, before[at].clip_index if i == 0 else None) for i, p in enumerate(parts)),
        *((c, c.clip_index) for c in before[at + 1 :]),
    ]
    clips = [c.model_copy(update={"clip_index": n}) for n, (c, _) in enumerate(seq, 1)]
    return chain_continuity(clips), {n: o for n, (_, o) in enumerate(seq, 1)}


def _position(clips: list[ClipScript], clip_index: int) -> int:
    return next((p for p, c in enumerate(clips) if c.clip_index == clip_index), -1)


def split_clip(
    clips: list[ClipScript],
    clip_index: int,
    steps: dict[int, StepRef],
    lines: dict[str, DialogueRef],
) -> ClipEdit | None:
    """Split clip `clip_index` into ≥2 contiguous clips obeying the key-action cap."""
    at = _position(clips, clip_index)
    if at < 0:
        return None
    clip = clips[at]
    chunk = [steps[i] for i in clip.step_indices if i in steps]
    if len(chunk) < 2:
        return None
    groups = partition_steps([s.key_action for s in chunk], 2)
    owner = [g for g, rng in enumerate(groups) for _ in rng]
    buckets: list[list[DialogueRef]] = [[] for _ in groups]
    for lid in clip.dialogue_line_ids:
        if lid in lines:
            pos = line_step_position(clip.omni_prompt, lines[lid], chunk)
            buckets[owner[pos]].append(lines[lid])
    parts = [
        make_clip(0, [chunk[i] for i in rng], bucket)
        for rng, bucket in zip(groups, buckets, strict=True)
    ]
    new, origin = _reindex(clips, at, parts)
    note = f"clip {clip_index} split into {len(parts)} clips ({[len(g) for g in groups]} steps)"
    return ClipEdit(new, origin, note)


def _words(clip: ClipScript, lines: dict[str, DialogueRef]) -> int:
    return sum(lines[d].word_count for d in clip.dialogue_line_ids if d in lines)


def _plan_moves(
    clips: list[ClipScript], at: int, lines: dict[str, DialogueRef]
) -> tuple[list[str], list[str]] | None:
    """Lines to move to the previous / next clip so clip `at` fits the word cap."""
    cap = CLIP_LIMITS.max_spoken_words
    ids = [d for d in clips[at].dialogue_line_ids if d in lines]
    room_prev = cap - _words(clips[at - 1], lines) if at > 0 else 0
    room_next = cap - _words(clips[at + 1], lines) if at + 1 < len(clips) else 0
    excess = _words(clips[at], lines) - cap
    to_prev: list[str] = []
    to_next: list[str] = []
    while excess > 0 and ids:
        tail, head = lines[ids[-1]].word_count, lines[ids[0]].word_count
        if tail <= room_next:
            to_next.insert(0, ids.pop())
            room_next, excess = room_next - tail, excess - tail
        elif head <= room_prev:
            to_prev.append(ids.pop(0))
            room_prev, excess = room_prev - head, excess - head
        else:
            return None
    return (to_prev, to_next) if excess <= 0 else None


def move_overflow_lines(
    clips: list[ClipScript],
    clip_index: int,
    steps: dict[int, StepRef],
    lines: dict[str, DialogueRef],
) -> ClipEdit | None:
    """Move trailing (leading) lines to the next (previous) clip until the cap holds."""
    at = _position(clips, clip_index)
    plan = _plan_moves(clips, at, lines) if at >= 0 else None
    if plan is None:
        return None
    to_prev, to_next = plan
    moved = set(to_prev) | set(to_next)
    if not moved:
        return None
    out = list(clips)
    edits = {at: [d for d in clips[at].dialogue_line_ids if d not in moved]}
    if to_prev:
        edits[at - 1] = [*clips[at - 1].dialogue_line_ids, *to_prev]
    if to_next:
        edits[at + 1] = [*to_next, *clips[at + 1].dialogue_line_ids]
    for pos, ids in edits.items():
        chunk = [steps[i] for i in clips[pos].step_indices if i in steps]
        rebuilt = make_clip(clips[pos].clip_index, chunk, [lines[d] for d in ids])
        out[pos] = rebuilt if chunk else clips[pos]
    note = f"moved {len(moved)} dialogue line(s) out of clip {clip_index}"
    return ClipEdit(
        chain_continuity(out), {c.clip_index: c.clip_index for c in out}, note
    )

"""Deterministic Omni clip builder and LLM clip normalizer (screenwriter-owned clips)."""

from __future__ import annotations

import logging
import math

from .models import (
    CLIP_MIN_S,
    MAX_CLIP_STEPS,
    MAX_CLIP_WORDS,
    ClipScript,
    clamp_clip_duration,
)
from .text import (
    DialogueRef,
    StepRef,
    compose_omni_prompt,
    ensure_dialogue_verbatim,
    strip_timestamps,
)
from .validation import validate_scene_clips

logger = logging.getLogger(__name__)

_SECONDS_PER_STEP: float = 3.0
_WORDS_PER_SECOND: float = 2.5


def _balanced_groups(n_items: int, n_groups: int) -> list[range]:
    """Split `range(n_items)` into `n_groups` contiguous ranges whose sizes differ by at most 1."""
    base, extra = divmod(n_items, n_groups)
    groups: list[range] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        groups.append(range(start, start + size))
        start += size
    return groups


def _assign_dialogue(lines: list[DialogueRef], n_clips: int) -> list[list[DialogueRef]]:
    """Spread lines proportionally across clips in spoken order, spilling forward past the word cap."""
    buckets: list[list[DialogueRef]] = [[] for _ in range(n_clips)]
    used = [0] * n_clips
    cur = 0
    for i, line in enumerate(lines):
        target = max(cur, (i * n_clips) // max(1, len(lines)))
        while target < n_clips - 1 and used[target] + line.word_count > MAX_CLIP_WORDS:
            target += 1
        buckets[target].append(line)
        used[target] += line.word_count
        cur = target
    return buckets


def _estimate_duration(n_steps: int, words: int) -> float:
    return clamp_clip_duration(
        max(n_steps * _SECONDS_PER_STEP, words / _WORDS_PER_SECOND + 1.5)
    )


def build_clips(steps: list[StepRef], lines: list[DialogueRef]) -> list[ClipScript]:
    """Deterministically partition steps into ≤3-action, ≤22-word, 8–10s Omni clips."""
    if not steps:
        return []
    total_words = sum(ln.word_count for ln in lines)
    n_clips = max(
        math.ceil(len(steps) / MAX_CLIP_STEPS),
        math.ceil(total_words / MAX_CLIP_WORDS),
        1,
    )
    n_clips = min(n_clips, len(steps))
    groups = _balanced_groups(len(steps), n_clips)
    dialogue = _assign_dialogue(lines, n_clips)
    clips: list[ClipScript] = []
    for pos, (grp, clip_lines) in enumerate(
        zip(groups, dialogue, strict=True), start=1
    ):
        chunk = [steps[i] for i in grp]
        words = sum(ln.word_count for ln in clip_lines)
        clips.append(
            ClipScript(
                clip_index=pos,
                duration_s=_estimate_duration(len(chunk), words),
                omni_prompt=compose_omni_prompt(chunk, clip_lines),
                step_indices=[s.step_index for s in chunk],
                dialogue_line_ids=[ln.line_id for ln in clip_lines],
                opening_state=chunk[0].pre_state,
                closing_state=chunk[-1].post_state,
            )
        )
    return chain_continuity(clips)


def chain_continuity(clips: list[ClipScript]) -> list[ClipScript]:
    """Force opening_state(N+1) = closing_state(N) so consecutive clips hand off cleanly."""
    out: list[ClipScript] = []
    for clip in clips:
        if out:
            clip = clip.model_copy(update={"opening_state": out[-1].closing_state})
        out.append(clip)
    return out


def _normalize_one(
    pos: int,
    raw: ClipScript,
    step_by_idx: dict[int, StepRef],
    line_by_id: dict[str, DialogueRef],
    id_map: dict[str, str],
    claimed: set[str],
) -> ClipScript:
    """Re-index, remap dialogue IDs, strip timestamps, and enforce verbatim dialogue for one clip."""
    dlg_ids: list[str] = []
    for raw_id in raw.dialogue_line_ids:
        pid = id_map.get(raw_id, raw_id)
        if pid in line_by_id and pid not in claimed:
            claimed.add(pid)
            dlg_ids.append(pid)
    lines = [line_by_id[d] for d in dlg_ids]
    chunk = [step_by_idx[i] for i in raw.step_indices if i in step_by_idx]
    prompt = strip_timestamps(raw.omni_prompt) or compose_omni_prompt(chunk, [])
    return ClipScript(
        clip_index=pos,
        duration_s=raw.duration_s,
        omni_prompt=ensure_dialogue_verbatim(prompt, lines),
        step_indices=list(raw.step_indices),
        dialogue_line_ids=dlg_ids,
        opening_state=raw.opening_state or (chunk[0].pre_state if chunk else ""),
        closing_state=raw.closing_state or (chunk[-1].post_state if chunk else ""),
    )


def _attach_unclaimed(
    clips: list[ClipScript], lines: list[DialogueRef], claimed: set[str]
) -> list[ClipScript]:
    """Append dialogue lines the LLM forgot to place onto the final clip (never drop speech)."""
    missing = [ln for ln in lines if ln.line_id not in claimed]
    if not missing or not clips:
        return clips
    last = clips[-1]
    clips[-1] = last.model_copy(
        update={
            "dialogue_line_ids": [
                *last.dialogue_line_ids,
                *(ln.line_id for ln in missing),
            ],
            "omni_prompt": ensure_dialogue_verbatim(last.omni_prompt, missing),
        }
    )
    return clips


def finalize_clips(
    scene_id: str,
    raw_clips: list[ClipScript],
    steps: list[StepRef],
    lines: list[DialogueRef],
    id_map: dict[str, str],
) -> list[ClipScript]:
    """Normalize LLM clips; rebuild deterministically when they still break partition/limit rules."""
    step_by_idx = {s.step_index: s for s in steps}
    line_by_id = {ln.line_id: ln for ln in lines}
    claimed: set[str] = set()
    clips = [
        _normalize_one(pos, raw, step_by_idx, line_by_id, id_map, claimed)
        for pos, raw in enumerate(raw_clips, start=1)
    ]
    clips = chain_continuity(_attach_unclaimed(clips, lines, claimed))
    words = {ln.line_id: ln.word_count for ln in lines}
    issues = validate_scene_clips(scene_id, [s.step_index for s in steps], clips, words)
    if clips and not issues:
        return clips
    logger.warning(
        "Screenwriter clips rejected; rebuilding deterministic Omni clip partition",
        extra={
            "who": "screenwriter",
            "where": "clips.builder.finalize_clips",
            "what": "clip_partition_rebuild",
            "scene_id": scene_id,
            "why": [i.code for i in issues] or ["no_clips"],
            "how": "deterministic_balanced_partition",
            "raw_clip_count": len(raw_clips),
            "min_duration_s": CLIP_MIN_S,
        },
    )
    return build_clips(steps, lines)

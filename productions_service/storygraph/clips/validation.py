"""O(steps + clips + shots) clip partition & shot↔clip mapping validation.

Issue codes are prefixed `S2_CLIP_*` (screenplay redo) or `S4_SHOT_CLIP_*` (shot redo)
so `stages_to_redo_for_issues` routes them to the responsible authoring stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .models import CLIP_MAX_S, CLIP_MIN_S, MAX_CLIP_STEPS, MAX_CLIP_WORDS, ClipScript
from .text import has_timestamps

CODE_MISSING: Final[str] = "S2_CLIPS_MISSING"
CODE_EMPTY: Final[str] = "S2_CLIP_EMPTY"
CODE_OUT_OF_RANGE: Final[str] = "S2_CLIP_STEP_OUT_OF_RANGE"
CODE_OVERLAP: Final[str] = "S2_CLIP_STEP_OVERLAP"
CODE_GAP: Final[str] = "S2_CLIP_STEP_GAP"
CODE_ORDER: Final[str] = "S2_CLIP_STEP_ORDER"
CODE_INDEX: Final[str] = "S2_CLIP_INDEX"
CODE_DURATION: Final[str] = "S2_CLIP_DURATION"
CODE_ACTIONS: Final[str] = "S2_CLIP_ACTION_LIMIT"
CODE_WORDS: Final[str] = "S2_CLIP_WORD_LIMIT"
CODE_DIALOGUE: Final[str] = "S2_CLIP_DIALOGUE_UNKNOWN"
CODE_TIMESTAMP: Final[str] = "S2_CLIP_TIMESTAMP"
CODE_PROMPT: Final[str] = "S2_CLIP_PROMPT_EMPTY"
CODE_CONTINUITY: Final[str] = "S2_CLIP_CONTINUITY"
CODE_SHOT_MISSING: Final[str] = "S4_SHOT_CLIP_MISSING"
CODE_SHOT_DURATION: Final[str] = "S4_SHOT_CLIP_DURATION"
CODE_SHOT_COVERAGE: Final[str] = "S4_SHOT_CLIP_COVERAGE"


@dataclass(frozen=True)
class ClipIssue:
    """Typed clip validation finding (always error severity)."""

    code: str
    node_id: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "node_id": self.node_id,
            "message": self.message,
        }


def validate_partition(
    scene_id: str, step_indices: list[int], clips: list[ClipScript]
) -> list[ClipIssue]:
    """Check clips partition `step_indices` contiguously: no gap, overlap, out-of-range, or reorder."""
    valid = set(step_indices)
    seen: set[int] = set()
    flat: list[int] = []
    issues: list[ClipIssue] = []
    for clip in clips:
        if not clip.step_indices:
            issues.append(
                ClipIssue(
                    CODE_EMPTY, scene_id, f"Clip {clip.clip_index} covers no steps."
                )
            )
        for idx in clip.step_indices:
            flat.append(idx)
            if idx not in valid:
                msg = f"Clip {clip.clip_index} references unknown step {idx}."
                issues.append(ClipIssue(CODE_OUT_OF_RANGE, scene_id, msg))
            elif idx in seen:
                msg = f"Step {idx} is covered by more than one clip (clip {clip.clip_index})."
                issues.append(ClipIssue(CODE_OVERLAP, scene_id, msg))
            seen.add(idx)
    missing = sorted(valid - seen)
    if missing:
        issues.append(
            ClipIssue(
                CODE_GAP, scene_id, f"Steps {missing} are not covered by any clip."
            )
        )
    if not issues and flat != step_indices:
        issues.append(
            ClipIssue(
                CODE_ORDER, scene_id, "Clips do not cover steps in screenplay order."
            )
        )
    return issues


def _validate_clip_body(
    scene_id: str, clip: ClipScript, dialogue_words: dict[str, int]
) -> list[ClipIssue]:
    """Check duration window, action/word limits, dialogue references, and timestamp-free prose."""
    label = f"Clip {clip.clip_index}"
    issues: list[ClipIssue] = []
    if not CLIP_MIN_S <= clip.duration_s <= CLIP_MAX_S:
        msg = f"{label} duration {clip.duration_s}s outside [{CLIP_MIN_S}, {CLIP_MAX_S}]s."
        issues.append(ClipIssue(CODE_DURATION, scene_id, msg))
    if len(clip.step_indices) > MAX_CLIP_STEPS:
        msg = f"{label} packs {len(clip.step_indices)} physical actions (max {MAX_CLIP_STEPS})."
        issues.append(ClipIssue(CODE_ACTIONS, scene_id, msg))
    unknown = [d for d in clip.dialogue_line_ids if d not in dialogue_words]
    if unknown:
        issues.append(
            ClipIssue(
                CODE_DIALOGUE,
                scene_id,
                f"{label} references unknown dialogue {unknown}.",
            )
        )
    words = sum(dialogue_words.get(d, 0) for d in clip.dialogue_line_ids)
    if words > MAX_CLIP_WORDS:
        msg = f"{label} carries {words} spoken words (max {MAX_CLIP_WORDS})."
        issues.append(ClipIssue(CODE_WORDS, scene_id, msg))
    if not clip.omni_prompt.strip():
        issues.append(
            ClipIssue(CODE_PROMPT, scene_id, f"{label} has an empty omni_prompt.")
        )
    elif has_timestamps(clip.omni_prompt):
        issues.append(
            ClipIssue(
                CODE_TIMESTAMP, scene_id, f"{label} omni_prompt contains timestamps."
            )
        )
    return issues


def _validate_sequence(scene_id: str, clips: list[ClipScript]) -> list[ClipIssue]:
    """Check 1..N clip numbering and closing_state(N) == opening_state(N+1)."""
    issues: list[ClipIssue] = []
    for pos, clip in enumerate(clips, start=1):
        if clip.clip_index != pos:
            msg = f"Clip at position {pos} has clip_index {clip.clip_index}."
            issues.append(ClipIssue(CODE_INDEX, scene_id, msg))
        if pos > 1 and clips[pos - 2].closing_state != clip.opening_state:
            msg = f"Clip {clip.clip_index} opening_state does not match clip {pos - 1} closing_state."
            issues.append(ClipIssue(CODE_CONTINUITY, scene_id, msg))
    return issues


def validate_scene_clips(
    scene_id: str,
    step_indices: list[int],
    clips: list[ClipScript],
    dialogue_words: dict[str, int],
) -> list[ClipIssue]:
    """Run every screenplay-level clip rule for one scene (no clips => S2 redo)."""
    if not clips:
        return [
            ClipIssue(
                CODE_MISSING,
                scene_id,
                f"Scene '{scene_id}' has no Omni clips; re-run S2.",
            )
        ]
    issues = validate_partition(scene_id, step_indices, clips)
    issues.extend(_validate_sequence(scene_id, clips))
    for clip in clips:
        issues.extend(_validate_clip_body(scene_id, clip, dialogue_words))
    return issues


@dataclass(frozen=True)
class ShotClipRef:
    """Typed contract of the shot fields needed to check the 1:1 clip mapping."""

    shot_id: str
    clip_index: int | None
    duration_s: float


def validate_shot_mapping(
    scene_id: str, clips: list[ClipScript], shots: list[ShotClipRef]
) -> list[ClipIssue]:
    """Check every clip maps to exactly one shot with an identical duration."""
    by_index = {c.clip_index: c for c in clips}
    used: dict[int, str] = {}
    issues: list[ClipIssue] = []
    for sh in shots:
        clip = by_index.get(sh.clip_index) if sh.clip_index is not None else None
        if clip is None:
            msg = f"Shot '{sh.shot_id}' is not linked to a clip of scene '{scene_id}'."
            issues.append(ClipIssue(CODE_SHOT_MISSING, sh.shot_id, msg))
            continue
        if clip.clip_index in used:
            msg = f"Clip {clip.clip_index} is mapped by both '{used[clip.clip_index]}' and '{sh.shot_id}'."
            issues.append(ClipIssue(CODE_SHOT_COVERAGE, sh.shot_id, msg))
        used[clip.clip_index] = sh.shot_id
        if abs(sh.duration_s - clip.duration_s) > 1e-6:
            msg = f"Shot '{sh.shot_id}' lasts {sh.duration_s}s but clip {clip.clip_index} is {clip.duration_s}s."
            issues.append(ClipIssue(CODE_SHOT_DURATION, sh.shot_id, msg))
    orphan = sorted(set(by_index) - set(used))
    if orphan:
        issues.append(
            ClipIssue(CODE_SHOT_COVERAGE, scene_id, f"Clips {orphan} have no Shot.")
        )
    return issues

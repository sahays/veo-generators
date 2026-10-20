"""Single source of truth for Omni clip authoring limits.

Consumed by the blocking spec linter (`lint/rules.py`), the deterministic clip builder and
validator (`clips/builder.py`, `clips/validation.py`), S7 remediation (`lint/remediate.py`)
and the screenwriter / director prompts, so an authoring agent is always told exactly the
rules the linter enforces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

SHOT_SIZES: Final[tuple[str, ...]] = ("ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS")
_SIZE_RANK: Final[dict[str, int]] = {s: i for i, s in enumerate(SHOT_SIZES)}
_MAX_FEEDBACK_ITEMS: Final[int] = 12


@dataclass(frozen=True)
class ClipLimits:
    """Per-clip load limits (one 8–10s Omni generation)."""

    min_duration_s: float = 8.0
    max_duration_s: float = 10.0
    max_clip_steps: int = 3
    max_key_actions: int = 2
    max_spoken_words: int = 20


@dataclass(frozen=True)
class LocomotionCameraPolicy:
    """Which cameras can follow a travelling character, and how S7 widens a bad one."""

    follow_moves: frozenset[str] = field(
        default_factory=lambda: frozenset({"track", "pan_l", "pan_r", "handheld"})
    )
    dolly_moves: frozenset[str] = field(
        default_factory=lambda: frozenset({"dolly_in", "dolly_out"})
    )
    dolly_min_size: str = "MS"
    static_sizes: frozenset[str] = field(
        default_factory=lambda: frozenset({"WS", "EWS"})
    )
    track_min_size: str = "MS"
    pan_min_size: str = "MLS"


@dataclass(frozen=True)
class FramingPolicy:
    """Omni camera limits: tight sizes drift (cuts, re-framing), so they are reserved for one
    in-place action on one subject; everything else renders at `default_size` and a tight
    size survives only as a framing intent. Set dressing is expected in frame only at
    `set_dressing_min_size` or wider."""

    tight_sizes: frozenset[str] = field(
        default_factory=lambda: frozenset({"ECU", "CU"})
    )
    default_size: str = "MS"
    tight_max_steps: int = 1
    set_dressing_min_size: str = "MS"


CLIP_LIMITS: Final[ClipLimits] = ClipLimits()
LOCOMOTION_CAMERA: Final[LocomotionCameraPolicy] = LocomotionCameraPolicy()
FRAMING: Final[FramingPolicy] = FramingPolicy()


def count_spoken_words(text: str) -> int:
    """Spoken words in `text`: whitespace tokens holding a letter/digit (script-agnostic).

    `re`'s `\\w` excludes combining marks (Devanagari matras), so regex word counting
    over-counts Hindi; whitespace tokenisation is correct for every supported language.
    """
    return sum(1 for tok in text.split() if any(ch.isalnum() for ch in tok))


def size_rank(size: str) -> int:
    """Ordinal of a shot size, tight (ECU=0) to wide (EWS=6); unknown sizes rank as MS."""
    return _SIZE_RANK.get(size, _SIZE_RANK["MS"])


def widen_to(size: str, floor: str) -> str:
    """`size`, widened to at least `floor` (never tightened)."""
    return size if size_rank(size) >= size_rank(floor) else floor


def camera_follows_locomotion(
    size: str, move: str, policy: LocomotionCameraPolicy = LOCOMOTION_CAMERA
) -> bool:
    """True when a camera of `size`/`move` can keep a travelling character in frame."""
    if move in policy.follow_moves:
        return True
    if move in policy.dolly_moves:
        return size_rank(size) >= size_rank(policy.dolly_min_size)
    return move == "static" and size in policy.static_sizes


def clip_rules_text(limits: ClipLimits = CLIP_LIMITS) -> str:
    """Screenwriter rule describing the clip partition limits the linter enforces."""
    return (
        "Arrange ALL steps into ordered `clips`: each clip covers 1–"
        f"{limits.max_clip_steps} CONTIGUOUS steps (every step exactly once, in order, no "
        f"gaps/overlap) with AT MOST {limits.max_key_actions} key actions (a key action is a "
        "step where a character travels — walks, runs, crosses, approaches, carries something "
        "to a place — or physically handles an object), carries AT MOST "
        f"{limits.max_spoken_words} spoken words in total, and picks `duration_s` between "
        f"{limits.min_duration_s} and {limits.max_duration_s}."
    )


def camera_rules_text(policy: LocomotionCameraPolicy = LOCOMOTION_CAMERA) -> str:
    """Director rule describing which cameras may cover a travelling character."""
    follow = "/".join(sorted(policy.follow_moves))
    dolly = "/".join(sorted(policy.dolly_moves))
    static = "/".join(sorted(policy.static_sizes))
    return (
        "When a clip has a character travelling (walk, run, stride, cross, approach, carry … "
        f"to, enter, exit, chase), its camera MUST follow: movement {follow}; {dolly} only at "
        f"shot_size {policy.dolly_min_size} or wider; static only at {static}. Never tilt or "
        "hold a close static shot on locomotion."
    )


def framing_rules_text(policy: FramingPolicy = FRAMING) -> str:
    """Director rule describing when a tight shot size is allowed (enforced by the linter)."""
    tight = "/".join(sorted(policy.tight_sizes))
    return (
        f"Default shot_size is {policy.default_size} or MLS. Use {tight} ONLY when the clip is "
        f"{policy.tight_max_steps} in-place action (no travelling) on a single subject; "
        f"otherwise a tight size is widened to {policy.default_size} and kept only as a "
        "framing intent in `camera_motion_intent`."
    )


def feedback_block(messages: Sequence[str], title: str) -> str:
    """Prompt section listing the exact linter messages the next draft must fix ('' if none)."""
    unique = list(dict.fromkeys(m.strip() for m in messages if m.strip()))
    if not unique:
        return ""
    lines = "\n".join(f"- {m}" for m in unique[:_MAX_FEEDBACK_ITEMS])
    return f"{title} (fix every one):\n{lines}\n\n"

"""Severity calibration rules shared by the rubric checks and offline re-grading.

Principles (identical on every attempt):
- Only concrete, observed defects (evidence citing a timestamp) may be HIGH.
- A score-threshold breach alone is MEDIUM, or LOW when within `NEAR_MISS_MARGIN` of the floor.
- An object that is simply outside the framing is not missing (LOW, informational).
- Camera deviations are never HIGH: shot-size only -> LOW; angle/move deviation -> MEDIUM.
- Hard cuts at/after `LATE_CUT_FRACTION` of the clip are trimmed before QA; earlier cuts -> MEDIUM.
"""

from __future__ import annotations

import re
from typing import Literal

Severity = Literal["high", "medium", "low"]

NEAR_MISS_MARGIN = 0.05
LATE_CUT_FRACTION = 0.75

_TIMESTAMP_RE = re.compile(r"\bt\s*=\s*\d+(?:\.\d+)?\s*s?", re.IGNORECASE)
_OUT_OF_FRAME_RE = re.compile(
    r"out of (?:the )?frame|outside (?:the )?(?:frame|framing|crop|view)"
    r"|not (?:seen|visible) (?:with)?in the fram|framed (?:crop|view|shot)"
    r"|off[- ]screen|cropped out|beyond the framing|due to framing",
    re.IGNORECASE,
)
_CAMERA_FLAG_TOKENS: tuple[str, ...] = (
    "framing",
    "camera",
    "angle",
    "shot_size",
    "zoom",
)
_OBJECT_FLAG_TOKENS: tuple[str, ...] = (
    "object",
    "prop",
    "duplicate",
    "missing",
    "vanish",
    "materializ",
    "support_surface",
    "floating",
    "inverted",
)
_MEASURED_FLAGS: frozenset[str] = frozenset(
    {"frozen_frame", "start_frame_bleed", "cut_discontinuity"}
)


def cites_timestamp(evidence: str) -> bool:
    """True when the evidence pins the observation to a clip time (e.g. 't=2.50s')."""
    return bool(_TIMESTAMP_RE.search(evidence or ""))


def mentions_out_of_frame(evidence: str) -> bool:
    """True when the evidence attributes non-visibility to the framing, not absence."""
    return bool(_OUT_OF_FRAME_RE.search(evidence or ""))


def score_breach_severity(value: float, floor: float) -> Severity:
    """A score floor breach alone is MEDIUM; a near miss (<= margin) is LOW."""
    return "low" if floor - value <= NEAR_MISS_MARGIN + 1e-9 else "medium"


def object_severity(kind: str, in_frame_expected: bool, evidence: str) -> Severity:
    """Missing/extra/state severity: needs the region in frame AND timestamped evidence."""
    if kind == "missing_object" and (
        not in_frame_expected or mentions_out_of_frame(evidence)
    ):
        return "low"
    if not in_frame_expected:
        return "low" if kind == "object_state" else "medium"
    return "high" if cites_timestamp(evidence) else "medium"


def camera_severity(size_ok: bool, angle_ok: bool, move_ok: bool) -> Severity | None:
    """Shot size alone -> LOW (Omni rarely honours sizes); angle/move -> MEDIUM; never HIGH."""
    if not (angle_ok and move_ok):
        return "medium"
    return None if size_ok else "low"


def cut_severity(cut_s: float, duration_s: float) -> Severity:
    """Late cuts (trimmed upstream when possible) are LOW; earlier cuts are MEDIUM."""
    if duration_s > 0.0 and cut_s >= LATE_CUT_FRACTION * duration_s:
        return "low"
    return "medium"


def flag_severity(flag: str, severe: bool) -> Severity:
    """Free-form flags: camera -> LOW; object flags defer to object verdicts -> MEDIUM."""
    low = flag.lower()
    if not severe or any(tok in low for tok in _CAMERA_FLAG_TOKENS):
        return "low"
    if low in _MEASURED_FLAGS:
        return "high"
    return "medium" if any(tok in low for tok in _OBJECT_FLAG_TOKENS) else "high"

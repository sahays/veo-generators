"""Story-quality checks: duplicate-beat detection and time-of-day continuity (Phase 5)."""

from __future__ import annotations

from .beats import Beat, BeatKind, collect_script_beats, collect_story_beats
from .dedup import DuplicateBeat, find_duplicate_beats
from .qa import (
    architect_guard_block,
    detect_story_issues,
    log_scene_duplicates,
    screenwriter_guard_block,
)
from .timeline import TimeRegression, find_time_regressions, tod_rank

__all__ = [
    "Beat",
    "BeatKind",
    "DuplicateBeat",
    "TimeRegression",
    "architect_guard_block",
    "collect_script_beats",
    "collect_story_beats",
    "detect_story_issues",
    "find_duplicate_beats",
    "find_time_regressions",
    "log_scene_duplicates",
    "screenwriter_guard_block",
    "tod_rank",
]

"""`time_of_day` continuity: continuous scenes must not move backwards in the day."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from ..schema import Scene

# Ordinal position in a day; generic labels ("day", "daytime") are intentionally unranked.
_TOD_RANK: Final[dict[str, int]] = {
    "dawn": 0,
    "sunrise": 0,
    "early morning": 1,
    "morning": 1,
    "late morning": 2,
    "noon": 2,
    "midday": 2,
    "afternoon": 3,
    "late afternoon": 3,
    "golden hour": 4,
    "sunset": 4,
    "dusk": 4,
    "evening": 4,
    "twilight": 4,
    "night": 5,
    "midnight": 5,
    "late night": 5,
}
_KEYS_LONGEST_FIRST: Final[tuple[str, ...]] = tuple(
    sorted(_TOD_RANK, key=len, reverse=True)
)
_NEW_DAY_FROM: Final[int] = 4  # evening/night -> dawn/morning reads as the next day
_NEW_DAY_TO: Final[int] = 1


@dataclass(frozen=True)
class TimeRegression:
    scene_id: str
    previous_scene_id: str
    time_of_day: str
    previous_time_of_day: str


def tod_rank(label: str) -> int | None:
    """Ordinal rank of a free-text time of day, or None when it is generic/unknown."""
    norm = " ".join(label.lower().replace("_", " ").split())
    if norm in _TOD_RANK:
        return _TOD_RANK[norm]
    return next((_TOD_RANK[k] for k in _KEYS_LONGEST_FIRST if k in norm), None)


def _regresses(prev: int, cur: int) -> bool:
    return cur < prev and not (prev >= _NEW_DAY_FROM and cur <= _NEW_DAY_TO)


def find_time_regressions(scenes: Iterable[Scene]) -> list[TimeRegression]:
    """Adjacent same-location scenes whose time of day goes backwards (single O(n log n) pass)."""
    ordered = sorted(scenes, key=lambda s: s.index)
    out: list[TimeRegression] = []
    for prev, cur in pairwise(ordered):
        if prev.location_id != cur.location_id:
            continue
        p_rank, c_rank = tod_rank(prev.time_of_day), tod_rank(cur.time_of_day)
        if p_rank is not None and c_rank is not None and _regresses(p_rank, c_rank):
            out.append(
                TimeRegression(cur.id, prev.id, cur.time_of_day, prev.time_of_day)
            )
    return out

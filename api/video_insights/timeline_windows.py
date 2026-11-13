"""Window and filmstrip planning for video timeline analysis.

Pure functions: no I/O and no service singletons. A long video is analysed in
consecutive windows so that no single model call has to describe more than
`max_window_sec` of footage; the windows partition `[0, duration]` exactly.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import Optional, Sequence

# Five minutes per model call. A live run on a 17-minute episode with 10-minute
# windows put two adjacent scenes in the wrong order and logged about a third
# of the dialogue; 5-minute windows got the scene order right and returned
# more than twice as many cues, for roughly 60% more output tokens.
DEFAULT_MAX_WINDOW_SEC = 300.0
# How far a window boundary may move to land on a detected hard cut.
SNAP_TOLERANCE_SEC = 15.0
# Windows shorter than this are never split again: a failure on so little
# footage is not a size problem, so halving it would only repeat the failure.
MIN_SPLIT_SEC = 20.0

FILMSTRIP_MAX_TILES = 120
FILMSTRIP_TILE_WIDTH = 160
FILMSTRIP_COLUMNS = 10
_FALLBACK_TILE_HEIGHT = 90


@dataclass(frozen=True)
class Window:
    """One analysed range of the full video, in seconds from its start."""

    index: int
    start_sec: float
    end_sec: float

    @property
    def length_sec(self) -> float:
        return self.end_sec - self.start_sec


def covers_whole_video(window: Window, duration_sec: float) -> bool:
    """True when `window` is the entire video rather than a part of it."""
    return window.start_sec <= 0 and window.end_sec >= duration_sec - 0.01


def nearest_cut(
    sorted_cuts: Sequence[float], target: float, tolerance: float
) -> Optional[float]:
    """Return the cut closest to `target` within `tolerance`, else None.

    `sorted_cuts` must be ascending; the lookup is a binary search. An exact
    tie between two cuts resolves to the earlier one.
    """
    pos = bisect_left(sorted_cuts, target)
    neighbours = sorted_cuts[max(0, pos - 1) : pos + 1]
    best = min(neighbours, key=lambda c: (abs(c - target), c), default=None)
    if best is None or abs(best - target) > tolerance:
        return None
    return best


def _interior_cuts(cuts: Sequence[float], low: float, high: float) -> list[float]:
    """Sorted, de-duplicated cuts strictly inside `(low, high)`."""
    return sorted({float(c) for c in cuts if low < c < high})


def plan_windows(
    duration_sec: float,
    cuts: list[float],
    max_window_sec: float = DEFAULT_MAX_WINDOW_SEC,
) -> list[Window]:
    """Partition `[0, duration_sec]` into consecutive analysis windows.

    Guarantees: the first window starts at 0, the last ends at `duration_sec`,
    each window starts exactly where the previous one ends, and no window is
    longer than `max_window_sec`. A video no longer than `max_window_sec` is a
    single window. Interior boundaries move to the nearest detected cut when one
    lies within the snap tolerance, so a window rarely ends mid-shot.
    """
    if max_window_sec <= 0:
        raise ValueError("max_window_sec must be positive")
    duration = max(0.0, float(duration_sec))
    if duration <= max_window_sec:
        return [Window(0, 0.0, duration)]
    tolerance = min(SNAP_TOLERANCE_SEC, max_window_sec * 0.05)
    # Even windows are sized with headroom for snapping on both ends, so a
    # snapped window still respects the hard `max_window_sec` cap.
    count = math.ceil(duration / (max_window_sec - 2 * tolerance))
    step = duration / count
    interior = _interior_cuts(cuts, 0.0, duration)
    bounds = [0.0]
    for k in range(1, count):
        target = k * step
        snapped = nearest_cut(interior, target, tolerance)
        bounds.append(round(target if snapped is None else snapped, 3))
    bounds.append(duration)
    return [Window(i, bounds[i], bounds[i + 1]) for i in range(count)]


def can_split(window: Window) -> bool:
    """True when both halves of `window` would still be worth analysing."""
    return window.length_sec >= 2 * MIN_SPLIT_SEC


def split_window(window: Window, cuts: Sequence[float]) -> tuple[Window, Window]:
    """Split `window` in two at its midpoint, snapped to a nearby cut.

    Both halves keep the parent's `index`: they are parts of one planned window
    and their results are recombined under that index.
    """
    mid = (window.start_sec + window.end_sec) / 2
    tolerance = min(SNAP_TOLERANCE_SEC, window.length_sec * 0.1)
    interior = _interior_cuts(cuts, window.start_sec, window.end_sec)
    snapped = nearest_cut(interior, mid, tolerance)
    boundary = round(mid if snapped is None else snapped, 3)
    return (
        Window(window.index, window.start_sec, boundary),
        Window(window.index, boundary, window.end_sec),
    )


def plan_filmstrip(
    duration_sec: float, width: int, height: int
) -> dict[str, int | float]:
    """Lay out the thumbnail sprite for a video (`FilmstripSpec` keys).

    Tile `i` shows the frame at `i * interval_sec`. The interval is a whole
    number of seconds, at least 1, chosen so the tile count stays within
    `FILMSTRIP_MAX_TILES`. Tiles are `FILMSTRIP_TILE_WIDTH` wide and keep the
    source aspect ratio (height rounded to an even number for the encoder).
    """
    duration = max(0.0, float(duration_sec))
    interval = float(max(1, math.ceil(duration / FILMSTRIP_MAX_TILES)))
    count = min(FILMSTRIP_MAX_TILES, max(1, math.ceil(duration / interval)))
    columns = min(count, FILMSTRIP_COLUMNS)
    tile_height = _FALLBACK_TILE_HEIGHT
    if width > 0 and height > 0:
        tile_height = max(2, 2 * round(FILMSTRIP_TILE_WIDTH * height / width / 2))
    return {
        "tile_width": FILMSTRIP_TILE_WIDTH,
        "tile_height": tile_height,
        "columns": columns,
        "rows": math.ceil(count / columns),
        "interval_sec": interval,
        "count": count,
    }

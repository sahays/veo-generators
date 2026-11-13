"""Smoothing, prominence-ranked local extrema and steepest declines of a series.

Pure functions over `[(t_sec, value)]` sorted by time. Extrema are strict interior
turning points (the first and last samples never qualify), so a flat or monotone
series has none and no sample can be both a peak and a valley.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from itertools import accumulate

from engagement_series import Point

MIN_PROMINENCE_RATIO = 0.1
MIN_DROP_RATIO = 0.2
_FLAT_TOLERANCE = 1e-9


def smooth(points: list[Point], window: int) -> list[Point]:
    """Centred moving average over `window` samples (prefix sums, O(n)).

    Near the ends the window shrinks symmetrically, so the curve is not shifted
    in time and the first and last samples are returned unchanged.
    """
    count = len(points)
    half = max(0, window) // 2
    if half == 0 or count < 3:
        return list(points)
    prefix = [0.0, *accumulate(value for _, value in points)]
    smoothed: list[Point] = []
    for index, (when, _) in enumerate(points):
        reach = min(half, index, count - 1 - index)
        low, high = index - reach, index + reach + 1
        smoothed.append((when, (prefix[high] - prefix[low]) / (high - low)))
    return smoothed


def _bases(values: list[float]) -> list[float]:
    """Lowest value between each sample and the previous strictly higher one.

    One pass with a monotonic stack of `(value, lowest since its own higher
    neighbour)`; every sample is pushed and popped at most once.
    """
    bases: list[float] = []
    stack: list[tuple[float, float]] = []
    for value in values:
        low = value
        while stack and stack[-1][0] <= value:
            low = min(low, stack.pop()[1])
        bases.append(low)
        stack.append((value, low))
    return bases


def _prominences(values: list[float]) -> list[float]:
    """Topographic prominence of every sample treated as a peak."""
    left = _bases(values)
    right = _bases(values[::-1])[::-1]
    return [v - max(lo, ro) for v, lo, ro in zip(values, left, right)]


def _turning_points(values: list[float]) -> list[tuple[int, bool]]:
    """Interior runs of equal values that are higher or lower than both sides.

    Returns `(middle index of the run, is_peak)`; a plateau yields one entry.
    """
    turns: list[tuple[int, bool]] = []
    count = len(values)
    start = 0
    while start < count:
        end = start
        while end + 1 < count and values[end + 1] == values[start]:
            end += 1
        if start > 0 and end < count - 1:
            before, level, after = values[start - 1], values[start], values[end + 1]
            if before < level > after:
                turns.append(((start + end) // 2, True))
            elif before > level < after:
                turns.append(((start + end) // 2, False))
        start = end + 1
    return turns


def _value_span(values: list[float]) -> float:
    """Range of the values, or 0.0 when they are equal up to rounding noise."""
    high, low = max(values), min(values)
    scale = max(1.0, abs(high), abs(low))
    return high - low if high - low > _FLAT_TOLERANCE * scale else 0.0


def _spaced(
    ranked: list[tuple[float, int]],
    times: list[float],
    min_spacing_sec: float,
    max_count: int,
) -> list[tuple[float, int]]:
    """Greedily keep the best candidates at least `min_spacing_sec` apart."""
    taken: list[float] = []
    kept: list[tuple[float, int]] = []
    for item in ranked:
        if len(kept) >= max_count:
            break
        when = times[item[1]]
        pos = bisect_left(taken, when)
        crowded_before = pos > 0 and when - taken[pos - 1] < min_spacing_sec
        crowded_after = pos < len(taken) and taken[pos] - when < min_spacing_sec
        if not (crowded_before or crowded_after):
            taken.insert(pos, when)
            kept.append(item)
    return kept


def find_extrema(
    points: list[Point],
    *,
    min_spacing_sec: float,
    max_count: int = 5,
    min_prominence_ratio: float = MIN_PROMINENCE_RATIO,
) -> list[dict]:
    """Local maxima and minima ranked by topographic prominence.

    Keeps turning points whose prominence is at least `min_prominence_ratio` of
    the series range, then up to `max_count` peaks and `max_count` valleys with
    at least `min_spacing_sec` between two of the same kind. Returns dicts with
    `kind` ("peak" | "valley"), `time_sec`, `value`, `prominence`, most prominent
    first. Pass a smoothed series to ignore sample-level noise.
    """
    values = [value for _, value in points]
    span = _value_span(values) if len(values) >= 3 else 0.0
    if span == 0.0:
        return []
    times = [when for when, _ in points]
    floor = span * min_prominence_ratio
    prominence = {True: _prominences(values), False: _prominences([-v for v in values])}
    ranked: dict[bool, list[tuple[float, int]]] = {True: [], False: []}
    for index, is_peak in _turning_points(values):
        if prominence[is_peak][index] >= floor:
            ranked[is_peak].append((-prominence[is_peak][index], index))
    found: list[dict] = []
    for is_peak, candidates in ranked.items():
        candidates.sort()
        for negated, index in _spaced(candidates, times, min_spacing_sec, max_count):
            found.append(
                {
                    "kind": "peak" if is_peak else "valley",
                    "time_sec": times[index],
                    "value": values[index],
                    "prominence": -negated,
                }
            )
    found.sort(key=lambda item: (-item["prominence"], item["time_sec"]))
    return found


def _window_declines(
    times: list[float], values: list[float], window_sec: float, floor: float
) -> list[tuple[float, int, int]]:
    """Largest fall starting at each sample within `window_sec` (sliding minimum).

    Returns `(-decline, -start index, index of the lowest later sample)`, so an
    ascending sort puts the largest fall first and, between equal falls, the one
    that starts latest (closest to the fall). A deque of indices with increasing
    values gives each window minimum in amortised O(1).
    """
    count = len(values)
    lowest: deque[int] = deque()
    reach = 0
    declines: list[tuple[float, int, int]] = []
    for start in range(count - 1):
        limit = times[start] + window_sec
        while reach < count and (times[reach] <= limit or reach <= start + 1):
            while lowest and values[lowest[-1]] > values[reach]:
                lowest.pop()
            lowest.append(reach)
            reach += 1
        while lowest and lowest[0] <= start:
            lowest.popleft()
        decline = values[start] - values[lowest[0]] if lowest else 0.0
        if decline > 0 and decline >= floor:
            declines.append((-decline, -start, lowest[0]))
    return declines


def find_drops(
    points: list[Point],
    *,
    window_sec: float,
    max_count: int = 3,
    min_drop_ratio: float = MIN_DROP_RATIO,
) -> list[dict]:
    """Steepest declines within `window_sec`, largest first, never overlapping.

    Each dict has `kind` ("drop"), `time_sec` and `value` where the decline
    starts, `prominence` (the size of the fall), plus `end_sec` / `end_value`
    where it bottoms out. Falls smaller than `min_drop_ratio` of the series range
    are ignored.
    """
    values = [value for _, value in points]
    span = _value_span(values) if len(values) >= 2 else 0.0
    if span == 0.0:
        return []
    times = [when for when, _ in points]
    declines = _window_declines(times, values, window_sec, span * min_drop_ratio)
    declines.sort()
    taken: list[tuple[float, float]] = []
    drops: list[dict] = []
    for negated, negated_start, end in declines:
        if len(drops) >= max_count:
            break
        start = -negated_start
        begin, finish = times[start], times[end]
        pos = bisect_left(taken, (begin, finish))
        if pos > 0 and taken[pos - 1][1] >= begin:
            continue
        if pos < len(taken) and taken[pos][0] <= finish:
            continue
        taken.insert(pos, (begin, finish))
        drops.append(
            {
                "kind": "drop",
                "time_sec": begin,
                "value": values[start],
                "prominence": -negated,
                "end_sec": finish,
                "end_value": values[end],
            }
        )
    drops.sort(key=lambda item: (-item["prominence"], item["time_sec"]))
    return drops

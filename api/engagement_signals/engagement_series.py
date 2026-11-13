"""Engagement signal series: the container, its time integral and resampling.

A series is piecewise constant: the value at `t` holds for `[t, t + interval_sec)`,
cut short when the next sample starts sooner. Everything here is pure (no I/O).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import accumulate

Point = tuple[float, float]

MAX_REPORT_POINTS = 2000


@dataclass
class SignalSeries:
    """One or more metrics sampled on a shared time axis (seconds from video start)."""

    metrics: dict[str, list[Point]]
    primary_metric: str
    interval_sec: float
    duration_sec: float
    time_column: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def points(self) -> list[Point]:
        """Samples of the primary metric."""
        return self.metrics.get(self.primary_metric, [])


class SeriesIntegral:
    """Prefix sums over a piecewise-constant series for O(log P) range averages."""

    def __init__(self, points: list[Point], interval_sec: float) -> None:
        interval = interval_sec if interval_sec > 0 else 1.0
        self._times = [t for t, _ in points]
        self._values = [v for _, v in points]
        self._lengths = [
            max(0.0, min(interval, nxt - cur))
            for cur, nxt in zip(self._times, self._times[1:])
        ]
        if points:
            self._lengths.append(interval)
        areas = (v * w for v, w in zip(self._values, self._lengths))
        self._area = [0.0, *accumulate(areas)]
        self._cover = [0.0, *accumulate(self._lengths)]

    @property
    def total_cover(self) -> float:
        """Seconds for which the series defines a value."""
        return self._cover[-1]

    @property
    def overall_mean(self) -> float:
        """Time-weighted mean of the whole series (0.0 when empty)."""
        return self._area[-1] / self._cover[-1] if self._cover[-1] > 0 else 0.0

    def _cumulative(self, x: float) -> tuple[float, float]:
        """Return `(area, covered seconds)` accumulated over `(-inf, x)`."""
        idx = bisect_right(self._times, x) - 1
        if idx < 0:
            return 0.0, 0.0
        part = min(x - self._times[idx], self._lengths[idx])
        return self._area[idx] + self._values[idx] * part, self._cover[idx] + part

    def over(self, start_sec: float, end_sec: float) -> tuple[float, float]:
        """Return `(area, covered seconds)` of the series inside `[start, end)`."""
        if end_sec <= start_sec:
            return 0.0, 0.0
        area_hi, cover_hi = self._cumulative(end_sec)
        area_lo, cover_lo = self._cumulative(start_sec)
        return area_hi - area_lo, cover_hi - cover_lo

    def mean(self, start_sec: float, end_sec: float) -> float | None:
        """Time-weighted mean inside `[start, end)`, or None without coverage."""
        area, cover = self.over(start_sec, end_sec)
        return area / cover if cover > 0 else None


def _bucket_means(points: list[Point], origin: float, width: float) -> list[Point]:
    """Average samples into `width`-second buckets anchored at `origin`."""
    sums: dict[int, tuple[float, int]] = {}
    for t, value in points:
        bucket = int((t - origin) // width)
        total, count = sums.get(bucket, (0.0, 0))
        sums[bucket] = (total + value, count + 1)
    return [
        (round(origin + bucket * width, 3), total / count)
        for bucket, (total, count) in sorted(sums.items())
    ]


def resample_series(
    series: SignalSeries, max_points: int = MAX_REPORT_POINTS
) -> SignalSeries:
    """Return `series` with at most ~`max_points` samples per metric (bucket means).

    All metrics share one bucket grid so they stay aligned. A series that is
    already small enough is returned unchanged.
    """
    longest = max((len(p) for p in series.metrics.values()), default=0)
    if longest <= max_points or max_points <= 0:
        return series
    starts = [p[0][0] for p in series.metrics.values() if p]
    ends = [p[-1][0] for p in series.metrics.values() if p]
    interval = series.interval_sec if series.interval_sec > 0 else 1.0
    origin = min(starts)
    span = max(ends) - origin + interval
    factor = max(2, math.ceil(span / interval / max_points))
    width = interval * factor
    return SignalSeries(
        metrics={
            label: _bucket_means(points, origin, width)
            for label, points in series.metrics.items()
        },
        primary_metric=series.primary_metric,
        interval_sec=width,
        duration_sec=series.duration_sec,
        time_column=series.time_column,
        warnings=list(series.warnings),
    )

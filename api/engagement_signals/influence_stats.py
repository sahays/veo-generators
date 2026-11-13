"""Deterministic engagement statistics: summary, per-segment and influence.

The series is piecewise constant (each value holds for `[t, t + interval)`), so
"engagement while X is present" is an overlap-weighted mean. A prefix-sum integral
plus binary search per range keeps the cost at O((P + A) log P) for P samples and
A ranges. Pure module: no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from engagement_series import Point, SeriesIntegral

ENTITY_KINDS: frozenset[str] = frozenset({"character", "object", "location"})
MIN_SUPPORT_SEC = 5.0
MIN_SUPPORT_FRACTION = 0.02
_ZERO_BASELINE = 1e-12

Range = tuple[float, float]


def percent_delta(value: float, baseline: float) -> float:
    """Percentage difference from `baseline`; 0.0 when the baseline is zero."""
    if abs(baseline) < _ZERO_BASELINE:
        return 0.0
    return round((value - baseline) / abs(baseline) * 100.0, 2)


def normalise_name(name: object) -> str:
    """Lowercase and collapse whitespace so equal names share an influence key."""
    return " ".join(str(name or "").lower().split())


def merge_ranges(ranges: Iterable[Range]) -> list[Range]:
    """Sort ranges and merge any that overlap or touch; empty ranges are dropped."""
    merged: list[Range] = []
    for start, end in sorted(r for r in ranges if r[1] > r[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _percentile(ordered: list[float], fraction: float) -> float:
    """Linear-interpolation percentile of an ascending list."""
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summary_stats(points: list[Point]) -> dict:
    """`ReportStats` for the sample values: avg, median, p75, min, max, std."""
    ordered = sorted(value for _, value in points)
    if not ordered:
        return dict.fromkeys(("avg", "median", "p75", "min", "max", "std"), 0.0)
    avg = math.fsum(ordered) / len(ordered)
    variance = math.fsum((v - avg) ** 2 for v in ordered) / len(ordered)
    return {
        "avg": round(avg, 4),
        "median": round(_percentile(ordered, 0.5), 4),
        "p75": round(_percentile(ordered, 0.75), 4),
        "min": round(ordered[0], 4),
        "max": round(ordered[-1], 4),
        "std": round(math.sqrt(variance), 4),
    }


def segment_stats(
    points: list[Point], interval_sec: float, segments: list[dict]
) -> list[dict]:
    """`ReportSegmentStat` per segment: time-weighted avg, delta vs overall, rank.

    Segments the signal does not cover are omitted. Rank 1 is the highest
    average; ties keep timeline order. Output follows the input segment order.
    """
    integral = SeriesIntegral(points, interval_sec)
    overall = integral.overall_mean
    stats: list[dict] = []
    for segment in segments:
        avg = integral.mean(float(segment["start_sec"]), float(segment["end_sec"]))
        if avg is None:
            continue
        stats.append(
            {
                "segment_id": segment["id"],
                "avg": round(avg, 4),
                "delta_pct": percent_delta(avg, overall),
                "rank": 0,
            }
        )
    by_avg = sorted(range(len(stats)), key=lambda i: (-stats[i]["avg"], i))
    for rank, position in enumerate(by_avg, start=1):
        stats[position]["rank"] = rank
    return stats


@dataclass
class _Presence:
    """Everything on the timeline that shares one influence key."""

    key: str
    ref_id: str | None
    name: str
    kind: str
    ranges: list[Range] = field(default_factory=list)


def _add_presence(
    groups: dict[str, _Presence],
    kind: str,
    name: object,
    ref_id: str | None,
    spans: Iterable[dict[str, Any]],
) -> None:
    """Add `spans` to the group for `(kind, name)`, creating it on first sight."""
    normalised = normalise_name(name)
    if not normalised:
        return
    key = f"{kind}:{normalised}"
    group = groups.get(key)
    if group is None:
        group = groups[key] = _Presence(key, ref_id, str(name).strip(), kind)
    group.ranges.extend(
        (float(span["start_sec"]), float(span["end_sec"])) for span in spans
    )


def _collect_presence(timeline: dict[str, Any]) -> list[_Presence]:
    """Group entity appearances, emotion spans and event spans by influence key."""
    groups: dict[str, _Presence] = {}
    for entity in timeline.get("entities") or []:
        kind = entity.get("kind")
        if kind in ENTITY_KINDS:
            spans = entity.get("appearances") or []
            _add_presence(groups, kind, entity.get("name"), entity.get("id"), spans)
    for emotion in timeline.get("emotions") or []:
        _add_presence(groups, "emotion", emotion.get("emotion"), None, [emotion])
    for event in timeline.get("events") or []:
        _add_presence(groups, "event", event.get("tag"), None, [event])
    return list(groups.values())


def _influence_entry(
    group: _Presence, integral: SeriesIntegral, support_floor_sec: float
) -> dict | None:
    """`ReportInfluence` for one key, or None when the signal never covers it."""
    ranges = merge_ranges(group.ranges)
    area = cover = 0.0
    for start, end in ranges:
        part_area, part_cover = integral.over(start, end)
        area += part_area
        cover += part_cover
    if cover <= 0:
        return None
    avg = area / cover
    return {
        "key": group.key,
        "ref_id": group.ref_id,
        "name": group.name,
        "kind": group.kind,
        "avg_during": round(avg, 4),
        "delta_pct": percent_delta(avg, integral.overall_mean),
        "coverage_sec": round(cover, 2),
        "coverage_pct": round(cover / integral.total_cover * 100.0, 2),
        "low_support": cover < support_floor_sec,
        "ranges": [
            {"start_sec": round(start, 2), "end_sec": round(end, 2)}
            for start, end in ranges
        ],
    }


def compute_influence(
    points: list[Point], interval_sec: float, timeline: dict
) -> list[dict]:
    """`ReportInfluence` for every entity, emotion name and event tag.

    For each key the overlapping ranges are merged, then engagement is averaged
    over the time the key is present, weighted by overlap with each sample.
    `low_support` marks keys present for less than 5 s, one sample interval or
    2% of the covered signal. Keys the signal never covers are dropped. Sorted
    with well-supported entries first, each group by `delta_pct` descending.
    """
    integral = SeriesIntegral(points, interval_sec)
    if integral.total_cover <= 0:
        return []
    floor = max(
        MIN_SUPPORT_SEC, interval_sec, MIN_SUPPORT_FRACTION * integral.total_cover
    )
    entries = [
        entry
        for group in _collect_presence(timeline)
        if (entry := _influence_entry(group, integral, floor)) is not None
    ]
    entries.sort(key=lambda e: (e["low_support"], -e["delta_pct"], e["key"]))
    return entries

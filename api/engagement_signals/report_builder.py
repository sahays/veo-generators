"""Assemble the deterministic part of an `EngagementReport`.

`build_report_core` computes every number in the report from the signal and the
timeline. The LLM-facing helpers (`explain_requests`, `apply_explanations`,
`recommendation_inputs`, `apply_recommendations`) only move prose in and out and
never let the model change a figure. Pure module: no I/O.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, replace
from typing import Any

from engagement_series import Point, SeriesIntegral, SignalSeries, resample_series
from influence_stats import (
    compute_influence,
    percent_delta,
    segment_stats,
    summary_stats,
)
from interval_index import TimelineIndex
from models_insights import ENGAGEMENT_REPORT_VERSION
from report_binding import (
    apply_explanations,
    apply_recommendations,
    empty_recommendations,
    recommendation_inputs,
)
from signal_peaks import find_drops, find_extrema, smooth

__all__ = [
    "apply_explanations",
    "apply_recommendations",
    "build_report_core",
    "explain_requests",
    "recommendation_inputs",
]

SIGNAL_KINDS: frozenset[str] = frozenset({"template", "barc"})
HOOK_MAX_SEC = 15.0
HOOK_FRACTION = 0.1
_KIND_ORDER: dict[str, int] = {"peak": 0, "valley": 1, "drop": 2}
_MAX_SMOOTH_WINDOW = 9
_SAMPLES_PER_SMOOTH_STEP = 40
_SPACING_FRACTION = 1 / 12
_DROP_WINDOW_FRACTION = 0.05
_MAX_DROP_WINDOW_SEC = 180.0
_PAD_FRACTION = 0.03
_MIN_PAD_SEC = 5.0
_MAX_PAD_SEC = 30.0
_KEY_JUNK_RE: re.Pattern[str] = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _Plan:
    """Analysis parameters derived from the length of the series."""

    interval_sec: float
    smooth_window: int
    min_spacing_sec: float
    drop_window_sec: float
    pad_sec: float


@dataclass(frozen=True)
class _Lanes:
    """Timeline lookups shared by every extremum."""

    index: TimelineIndex
    duration_sec: float


def _plan(points: list[Point], interval_sec: float) -> _Plan:
    """Scale smoothing, spacing and context windows to the series."""
    span = points[-1][0] - points[0][0] + interval_sec if points else 0.0
    steps = round(len(points) / _SAMPLES_PER_SMOOTH_STEP)
    return _Plan(
        interval_sec=interval_sec,
        smooth_window=min(_MAX_SMOOTH_WINDOW, max(1, steps)) | 1,
        min_spacing_sec=max(2 * interval_sec, span * _SPACING_FRACTION),
        drop_window_sec=max(
            3 * interval_sec, min(_MAX_DROP_WINDOW_SEC, span * _DROP_WINDOW_FRACTION)
        ),
        pad_sec=min(_MAX_PAD_SEC, max(_MIN_PAD_SEC, span * _PAD_FRACTION)),
    )


def _within_video(series: SignalSeries, duration_sec: float) -> SignalSeries:
    """Drop samples that start at or after the end of the video."""
    if duration_sec <= 0:
        return series
    metrics = {
        label: points[: bisect_left(points, duration_sec, key=lambda p: p[0])]
        for label, points in series.metrics.items()
    }
    if not metrics.get(series.primary_metric):
        raise ValueError(
            "The engagement signal has no samples inside the video's duration; "
            "check the alignment offset."
        )
    return replace(series, metrics=metrics)


def _signal_meta(series: SignalSeries, meta: dict[str, Any]) -> dict:
    """`ReportSignalMeta`: caller-supplied identity plus facts from the series."""
    kind = meta.get("kind")
    if kind not in SIGNAL_KINDS:
        raise ValueError(f"Unknown engagement signal kind: {kind!r}.")
    simulated = kind == "template"
    unit = "index" if simulated else ("%" if "%" in series.primary_metric else "")
    return {
        "kind": kind,
        "template_id": meta.get("template_id") if simulated else None,
        "label": str(meta.get("label") or series.primary_metric),
        "simulated": simulated,
        "primary_metric": series.primary_metric,
        "unit": str(meta.get("unit") or unit),
        "offset_sec": round(float(meta.get("offset_sec") or 0.0), 3),
        "point_count": len(series.points),
        "interval_sec": series.interval_sec,
    }


def _rounded(points: list[Point]) -> list[list[float]]:
    """Points as JSON-ready `[t_sec, value]` pairs."""
    return [[round(when, 3), round(value, 4)] for when, value in points]


def _metrics(series: SignalSeries) -> list[dict]:
    """`ReportMetric` list with unique keys, primary metric first."""
    labels = sorted(series.metrics, key=lambda label: label != series.primary_metric)
    metrics: list[dict] = []
    used: set[str] = set()
    for position, label in enumerate(labels, start=1):
        key = _KEY_JUNK_RE.sub("_", label.lower()).strip("_") or "metric"
        key = f"{key}_{position}" if key in used else key
        used.add(key)
        metrics.append(
            {
                "key": key,
                "label": label,
                "primary": label == series.primary_metric,
                "points": _rounded(series.metrics[label]),
            }
        )
    return metrics


def _extremum(
    found: dict, ident: str, plan: _Plan, baseline: float, lanes: _Lanes
) -> dict:
    """`ReportExtremum` (prose empty) with its segment and context window."""
    when = found["time_sec"]
    until = found.get("end_sec", when) + plan.interval_sec + plan.pad_sec
    segment = lanes.index.segment_at(when)
    return {
        "id": ident,
        "kind": found["kind"],
        "time_sec": round(when, 2),
        "value": round(found["value"], 4),
        "prominence": round(found["prominence"], 4),
        "delta_pct": percent_delta(found["value"], baseline),
        "window": {
            "start_sec": round(max(0.0, when - plan.pad_sec), 2),
            "end_sec": round(min(lanes.duration_sec, until), 2),
        },
        "segment_id": segment["id"] if segment else None,
        "title": "",
        "explanation": "",
        "drivers": [],
    }


def _extrema(
    smoothed: list[Point], plan: _Plan, baseline: float, lanes: _Lanes
) -> list[dict]:
    """Peaks, valleys and drops of the smoothed curve with rank-based ids."""
    found = find_extrema(smoothed, min_spacing_sec=plan.min_spacing_sec)
    found += find_drops(smoothed, window_sec=plan.drop_window_sec)
    ranks = dict.fromkeys(_KIND_ORDER, 0)
    extrema: list[dict] = []
    for item in found:
        ranks[item["kind"]] += 1
        ident = f"{item['kind']}-{ranks[item['kind']]}"
        extrema.append(_extremum(item, ident, plan, baseline, lanes))
    extrema.sort(key=lambda e: _KIND_ORDER[e["kind"]])
    return extrema


def _kpis(
    points: list[Point], interval_sec: float, extrema: list[dict], duration: float
) -> dict:
    """`ReportKpis` except `avg`: headline figures of the raw primary series.

    `biggest_drop.delta` is negative (the change in value over the decline).
    """
    if not points:
        return {"peak": None, "low": None, "biggest_drop": None, "hook_avg": None}
    top = max(points, key=lambda p: p[1])
    low = min(points, key=lambda p: p[1])
    drop = next((e for e in extrema if e["kind"] == "drop"), None)
    hook_sec = min(HOOK_MAX_SEC, HOOK_FRACTION * duration)
    hook = SeriesIntegral(points, interval_sec).mean(0.0, hook_sec)
    biggest = None
    if drop is not None:
        biggest = {"time_sec": drop["time_sec"], "delta": -drop["prominence"]}
    return {
        "peak": {"time_sec": round(top[0], 2), "value": round(top[1], 4)},
        "low": {"time_sec": round(low[0], 2), "value": round(low[1], 4)},
        "biggest_drop": biggest,
        "hook_avg": None if hook is None else round(hook, 4),
    }


def build_report_core(timeline: dict, series: SignalSeries, signal_meta: dict) -> dict:
    """Build an `EngagementReport` with every deterministic field filled in.

    `signal_meta` carries `kind` ("template" | "barc") and optionally
    `template_id`, `label`, `unit` and `offset_sec`; the rest of the report's
    `signal` block comes from the series. Samples after the end of the video
    are discarded and long series are bucketed to at most 2000 points. Extrema
    are detected on the smoothed curve (their `time_sec` / `value` refer to it)
    and listed as peaks, valleys, then drops, each most prominent first. Prose
    fields are left empty for `apply_explanations` / `apply_recommendations`.
    Raises `ValueError` if no sample falls inside the video or the kind is
    unknown.
    """
    video_sec = float(timeline.get("duration_sec") or 0.0)
    series = resample_series(_within_video(series, video_sec))
    points = series.points
    duration = video_sec or series.duration_sec
    plan = _plan(points, series.interval_sec)
    smoothed = smooth(points, plan.smooth_window)
    stats = summary_stats(points)
    lanes = _Lanes(TimelineIndex(timeline), duration)
    extrema = _extrema(smoothed, plan, stats["avg"], lanes)
    segments = timeline.get("segments") or []
    return {
        "schema_version": ENGAGEMENT_REPORT_VERSION,
        "duration_sec": round(duration, 2),
        "signal": _signal_meta(series, signal_meta),
        "metrics": _metrics(series),
        "smoothed": _rounded(smoothed),
        "stats": stats,
        "extrema": extrema,
        "segments": segment_stats(points, series.interval_sec, segments),
        "influence": compute_influence(points, series.interval_sec, timeline),
        "recommendations": empty_recommendations(),
        "kpis": {
            "avg": stats["avg"],
            **_kpis(points, series.interval_sec, extrema, duration),
        },
    }


def explain_requests(report: dict, timeline: dict) -> list[dict]:
    """One compact request per extremum for the explanation prompt.

    Each is `{id, kind, time_sec, value, delta_pct, context}` where `context` is
    the timeline slice inside the extremum's window.
    """
    index = TimelineIndex(timeline)
    return [
        {
            "id": extremum["id"],
            "kind": extremum["kind"],
            "time_sec": extremum["time_sec"],
            "value": extremum["value"],
            "delta_pct": extremum["delta_pct"],
            "context": index.slice(
                extremum["window"]["start_sec"], extremum["window"]["end_sec"]
            ),
        }
        for extremum in report.get("extrema") or []
    ]

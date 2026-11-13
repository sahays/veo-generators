"""Deterministic assembly of the engagement report."""

from __future__ import annotations

import copy
import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest
from engagement_series import SignalSeries
from influence_stats import summary_stats
from report_builder import build_report_core, explain_requests
from signal_parser import parse_signal_csv

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "engagement_signals"
    / "timeline_small.json"
)
_METRIC = "Engagement index"
_TEMPLATE_META = {"kind": "template", "template_id": "jumpy", "label": "Jumpy"}


def _timeline() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _wave_value(t: float) -> float:
    """50 with a bump to 80 at t=45 and a dip to 25 at t=75."""
    bump = 30.0 * math.exp(-(((t - 45.0) / 8.0) ** 2))
    dip = 25.0 * math.exp(-(((t - 75.0) / 8.0) ** 2))
    return 50.0 + bump - dip


def _wave(step: int = 5, duration: int = 120) -> SignalSeries:
    points = [(float(t), _wave_value(t)) for t in range(0, duration, step)]
    return SignalSeries({_METRIC: points}, _METRIC, float(step), float(duration))


def _by_id(report: dict) -> dict[str, dict]:
    return {extremum["id"]: extremum for extremum in report["extrema"]}


def test_core_report_fills_every_deterministic_field() -> None:
    series = _wave()
    report = build_report_core(_timeline(), series, _TEMPLATE_META)
    assert set(report) == {
        "schema_version",
        "duration_sec",
        "signal",
        "metrics",
        "smoothed",
        "stats",
        "extrema",
        "segments",
        "influence",
        "recommendations",
        "kpis",
    }
    assert report["schema_version"] == "engagement-report-v1"
    assert report["duration_sec"] == 120.0
    assert report["signal"] == {
        "kind": "template",
        "template_id": "jumpy",
        "label": "Jumpy",
        "simulated": True,
        "primary_metric": _METRIC,
        "unit": "index",
        "offset_sec": 0.0,
        "point_count": 24,
        "interval_sec": 5.0,
    }
    (metric,) = report["metrics"]
    assert (metric["key"], metric["label"], metric["primary"]) == (
        "engagement_index",
        _METRIC,
        True,
    )
    assert metric["points"][9] == [45.0, 80.0]
    assert report["stats"] == summary_stats(series.points)
    assert report["recommendations"] == {
        "headline": "",
        "do_more": [],
        "do_less": [],
        "segment_fixes": [],
    }
    assert [s["segment_id"] for s in report["segments"]] == [
        "seg-1",
        "seg-2",
        "seg-3",
        "seg-4",
    ]
    assert {s["segment_id"]: s["rank"] for s in report["segments"]}["seg-2"] == 1
    assert "character:asha" in {entry["key"] for entry in report["influence"]}


def test_extrema_get_rank_ids_segments_and_clamped_windows() -> None:
    report = build_report_core(_timeline(), _wave(), _TEMPLATE_META)
    extrema = _by_id(report)
    assert list(extrema) == ["peak-1", "valley-1", "drop-1", "drop-2"]
    peak, valley, drop = extrema["peak-1"], extrema["valley-1"], extrema["drop-1"]
    assert (peak["kind"], peak["time_sec"], peak["value"]) == ("peak", 45.0, 80.0)
    assert peak["segment_id"] == "seg-2"
    assert peak["prominence"] == pytest.approx(30.0, abs=0.01)  # 80 down to ~50
    avg = report["stats"]["avg"]
    assert peak["delta_pct"] == round((80.0 - avg) / avg * 100, 2)
    # 5 s either side of the 5 s sample that starts at 45.
    assert peak["window"] == {"start_sec": 40.0, "end_sec": 55.0}
    assert (valley["time_sec"], valley["value"]) == (75.0, 25.0)
    assert valley["segment_id"] == "seg-3"
    assert valley["delta_pct"] < 0 < peak["delta_pct"]
    assert (drop["kind"], drop["time_sec"], drop["segment_id"]) == (
        "drop",
        45.0,
        "seg-2",
    )
    assert drop["window"] == {"start_sec": 40.0, "end_sec": 70.0}  # covers 45 -> 60
    assert extrema["drop-2"]["prominence"] < drop["prominence"]
    for extremum in report["extrema"]:
        assert (extremum["title"], extremum["explanation"]) == ("", "")
        assert extremum["drivers"] == []
        assert 0.0 <= extremum["window"]["start_sec"] < extremum["window"]["end_sec"]
        assert extremum["window"]["end_sec"] <= 120.0


def test_windows_are_clamped_to_the_video_and_gaps_have_no_segment() -> None:
    timeline = {**_timeline(), "duration_sec": 600.0}
    timeline["segments"] = timeline["segments"][:1]  # only 0-30 is segmented
    values = [10.0, 90.0] + [10.0] * 116 + [90.0, 10.0]
    points = [(float(5 * i), value) for i, value in enumerate(values)]
    series = SignalSeries({_METRIC: points}, _METRIC, 5.0, 600.0)
    report = build_report_core(timeline, series, _TEMPLATE_META)
    extrema = _by_id(report)
    # Context padding is 3% of 600 s = 18 s; it may not leave the video.
    assert extrema["peak-1"]["time_sec"] == 5.0
    assert extrema["peak-1"]["window"] == {"start_sec": 0.0, "end_sec": 28.0}
    assert extrema["peak-1"]["segment_id"] == "seg-1"
    assert extrema["peak-2"]["time_sec"] == 585.0
    assert extrema["peak-2"]["window"] == {"start_sec": 567.0, "end_sec": 600.0}
    assert extrema["valley-1"]["time_sec"] == 295.0  # middle of the low plateau
    assert extrema["valley-1"]["window"] == {"start_sec": 277.0, "end_sec": 318.0}
    assert extrema["valley-1"]["segment_id"] is None
    # Two equal falls: the earlier one ranks first.
    assert extrema["drop-1"]["window"] == {"start_sec": 0.0, "end_sec": 38.0}
    assert extrema["drop-2"]["window"] == {"start_sec": 572.0, "end_sec": 600.0}


def test_kpis_come_from_the_raw_series() -> None:
    series = _wave()
    report = build_report_core(_timeline(), series, _TEMPLATE_META)
    values = [value for _, value in series.points]
    hook = (5 * values[0] + 5 * values[1] + 2 * values[2]) / 12  # first 12 s
    assert report["kpis"] == {
        "avg": report["stats"]["avg"],
        "peak": {"time_sec": 45.0, "value": 80.0},
        "low": {"time_sec": 75.0, "value": 25.0},
        "biggest_drop": {
            "time_sec": 45.0,
            "delta": -_by_id(report)["drop-1"]["prominence"],
        },
        "hook_avg": round(hook, 4),
    }
    assert report["kpis"]["biggest_drop"]["delta"] < -25
    # 120 s video: the hook is the first 12 s, so the third sample counts for 2 s.
    opening = [(0.0, 10.0), (5.0, 90.0), (10.0, 10.0), (15.0, 10.0)]
    spiky = SignalSeries({_METRIC: opening}, _METRIC, 5.0, 20.0)
    spiky_report = build_report_core(_timeline(), spiky, _TEMPLATE_META)
    assert spiky_report["kpis"]["hook_avg"] == round((50 + 450 + 20) / 12, 4)
    # Long video: the hook is capped at the first 15 s.
    long = _wave(step=5, duration=600)
    long_timeline = {**_timeline(), "duration_sec": 600.0}
    long_values = [value for _, value in long.points]
    long_report = build_report_core(long_timeline, long, _TEMPLATE_META)
    assert long_report["kpis"]["hook_avg"] == round(sum(long_values[:3]) / 3, 4)


def test_monotone_signal_reports_no_extrema_and_no_drop() -> None:
    points = [(float(t), 20.0 + t / 4) for t in range(0, 120, 5)]
    series = SignalSeries({_METRIC: points}, _METRIC, 5.0, 120.0)
    report = build_report_core(_timeline(), series, _TEMPLATE_META)
    assert report["extrema"] == []
    assert report["kpis"]["biggest_drop"] is None
    assert report["kpis"]["peak"] == {"time_sec": 115.0, "value": 48.75}
    assert report["kpis"]["low"] == {"time_sec": 0.0, "value": 20.0}


def test_barc_csv_flows_through_to_a_measured_report() -> None:
    rows = "".join(
        f'01/03/2024,20:{m:02d}:00,20:{m:02d}:59,1,"{1000 + 10 * m:,}",{_wave_value(m * 60) / 100:.3f}%,5\n'
        for m in range(2)
    )
    header = "Date,Start Time,End Time,Duration (Mins),Impressions ('000s),TVR (%),Reach ('000s)\n"
    series = parse_signal_csv((header + rows).encode(), offset_sec=15.0)
    meta = {
        "kind": "barc",
        "label": "evening.csv",
        "offset_sec": 15.0,
        "template_id": "x",
    }
    report = build_report_core(_timeline(), series, meta)
    assert report["signal"] == {
        "kind": "barc",
        "template_id": None,
        "label": "evening.csv",
        "simulated": False,
        "primary_metric": "TVR (%)",
        "unit": "%",
        "offset_sec": 15.0,
        "point_count": 2,
        "interval_sec": 60.0,
    }
    assert [(m["key"], m["primary"]) for m in report["metrics"]] == [
        ("tvr", True),
        ("impressions_000s", False),
        ("reach_000s", False),
    ]
    assert report["metrics"][1]["points"] == [[15.0, 1000.0], [75.0, 1010.0]]
    assert [p[0] for p in report["smoothed"]] == [15.0, 75.0]
    assert report["kpis"]["hook_avg"] is None  # the signal starts after the 12 s hook


def test_samples_after_the_end_of_the_video_are_discarded() -> None:
    series = _wave(step=5, duration=300)  # video is only 120 s long
    report = build_report_core(_timeline(), series, _TEMPLATE_META)
    assert report["signal"]["point_count"] == 24
    assert report["metrics"][0]["points"][-1][0] == 115.0
    assert report["duration_sec"] == 120.0
    assert report["stats"] == summary_stats(series.points[:24])
    late = SignalSeries({_METRIC: [(500.0, 1.0), (505.0, 2.0)]}, _METRIC, 5.0, 510.0)
    with pytest.raises(ValueError, match="no samples inside the video's duration"):
        build_report_core(_timeline(), late, _TEMPLATE_META)
    with pytest.raises(ValueError, match="Unknown engagement signal kind"):
        build_report_core(_timeline(), _wave(), {"kind": "predicted"})


def test_long_series_is_bucketed_and_smoothed() -> None:
    timeline = {**_timeline(), "duration_sec": 6000.0}
    points = [(float(t), float(t % 3)) for t in range(6000)]  # 0,1,2 repeating
    series = SignalSeries({_METRIC: points}, _METRIC, 1.0, 6000.0)
    report = build_report_core(timeline, series, {"kind": "barc"})
    assert report["signal"]["point_count"] == 2000
    assert report["signal"]["interval_sec"] == 3.0
    assert report["metrics"][0]["points"][:3] == [[0.0, 1.0], [3.0, 1.0], [6.0, 1.0]]
    assert report["stats"]["avg"] == 1.0
    assert len(series.points) == 6000  # the caller's series is left alone
    # 400 samples -> a 9-sample window flattens single-sample noise.
    noisy = [(float(t), 50.0 + (8.0 if t % 2 else -8.0)) for t in range(400)]
    wide = {**_timeline(), "duration_sec": 400.0}
    smooth_report = build_report_core(
        wide, SignalSeries({_METRIC: noisy}, _METRIC, 1.0, 400.0), {"kind": "barc"}
    )
    middle = [value for _, value in smooth_report["smoothed"][10:390]]
    assert max(middle) - min(middle) < 2.0
    # Extrema are read off the smoothed curve, KPIs off the raw samples.
    assert all(49.0 < e["value"] < 51.0 for e in smooth_report["extrema"])
    assert smooth_report["kpis"]["peak"]["value"] == 58.0


def test_explain_requests_carry_a_context_slice_per_extremum() -> None:
    timeline = _timeline()
    report = build_report_core(timeline, _wave(), _TEMPLATE_META)
    requests = explain_requests(report, timeline)
    assert [request["id"] for request in requests] == [
        e["id"] for e in report["extrema"]
    ]
    peak = requests[0]
    assert set(peak) == {"id", "kind", "time_sec", "value", "delta_pct", "context"}
    assert (peak["kind"], peak["time_sec"], peak["value"]) == ("peak", 45.0, 80.0)
    assert peak["delta_pct"] == report["extrema"][0]["delta_pct"]
    context = peak["context"]
    assert (context["start_sec"], context["end_sec"]) == (40.0, 55.0)
    assert [segment["id"] for segment in context["segments"]] == ["seg-2"]
    assert [cue["text"] for cue in context["cues"]] == ["I hope I am not too early."]
    assert [entity["name"] for entity in context["entities"]] == [
        "Kitchen",
        "Asha",
        "Judge",
    ]
    assert [moment["label"] for moment in context["key_moments"]] == [
        "Judge arrives early"
    ]
    valley = requests[1]["context"]
    assert [cue["text"] for cue in valley["cues"]] == ["Upbeat percussion"]
    assert valley["entities"] == []


def test_building_a_report_leaves_its_inputs_untouched() -> None:
    timeline, series = _timeline(), _wave()
    before = (copy.deepcopy(timeline), copy.deepcopy(series), dict(_TEMPLATE_META))
    first = build_report_core(timeline, series, _TEMPLATE_META)
    assert (timeline, series, _TEMPLATE_META) == before
    assert build_report_core(timeline, series, _TEMPLATE_META) == first
    assert json.loads(json.dumps(first)) == first  # plain JSON-ready data
    # A series restored from a JSON checkpoint ([t, v] lists) gives the same report.
    restored = SignalSeries(**json.loads(json.dumps(dataclasses.asdict(series))))
    assert build_report_core(timeline, restored, _TEMPLATE_META) == first

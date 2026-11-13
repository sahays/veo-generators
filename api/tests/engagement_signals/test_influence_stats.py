"""Overlap-weighted influence, per-segment and summary statistics."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

import pytest
from engagement_series import SeriesIntegral
from influence_stats import (
    compute_influence,
    merge_ranges,
    segment_stats,
    summary_stats,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "engagement_signals"
    / "timeline_small.json"
)
Point = tuple[float, float]
# Two one-minute samples: 10 for the first minute, 30 for the second.
_MINUTES: list[Point] = [(0.0, 10.0), (60.0, 30.0)]


def _timeline() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _entity(name: str, *spans: tuple[float, float], kind: str = "character") -> dict:
    return {
        "id": f"ent-{name}",
        "name": name,
        "kind": kind,
        "appearances": [{"start_sec": a, "end_sec": b} for a, b in spans],
    }


def _by_key(entries: list[dict]) -> dict[str, dict]:
    return {entry["key"]: entry for entry in entries}


def test_entity_inside_a_minute_sample_gets_that_samples_value() -> None:
    """On screen 00:10-00:50 of a minute-long sample.

    Testing only each sample's start instant (t=0, t=60) against the range gives
    this entity no weight at all; overlap weighting gives it 40 s at value 10.
    """
    timeline = {"entities": [_entity("Asha", (10.0, 50.0))]}
    (entry,) = compute_influence(_MINUTES, 60.0, timeline)
    assert entry == {
        "key": "character:asha",
        "ref_id": "ent-Asha",
        "name": "Asha",
        "kind": "character",
        "avg_during": 10.0,
        "delta_pct": -50.0,  # overall mean is 20
        "coverage_sec": 40.0,
        "coverage_pct": 33.33,
        "low_support": True,  # 40 s is less than one 60 s sample
        "ranges": [{"start_sec": 10.0, "end_sec": 50.0}],
    }


def test_range_straddling_two_samples_is_weighted_by_overlap() -> None:
    timeline = {
        "entities": [
            _entity("Even", (40.0, 80.0)),  # 20 s at 10 + 20 s at 30
            _entity("Late", (50.0, 120.0)),  # 10 s at 10 + 60 s at 30
        ]
    }
    entries = _by_key(compute_influence(_MINUTES, 60.0, timeline))
    assert entries["character:even"]["avg_during"] == 20.0
    assert entries["character:even"]["delta_pct"] == 0.0
    assert entries["character:late"]["avg_during"] == round(1900 / 70, 4)
    assert entries["character:late"]["coverage_sec"] == 70.0
    assert entries["character:late"]["low_support"] is False


def test_overlapping_appearances_are_merged_not_double_counted() -> None:
    timeline = {"entities": [_entity("Asha", (0.0, 40.0), (20.0, 80.0), (80.0, 90.0))]}
    (entry,) = compute_influence(_MINUTES, 60.0, timeline)
    # Merged to 0-90: 60 s at 10 and 30 s at 30. Counting 20-40 twice gives 15.45.
    assert entry["avg_during"] == round(1500 / 90, 4)
    assert entry["coverage_sec"] == 90.0
    assert entry["ranges"] == [{"start_sec": 0.0, "end_sec": 90.0}]
    assert merge_ranges(
        [(5.0, 9.0), (1.0, 3.0), (3.0, 4.0), (8.0, 12.0), (7.0, 7.0)]
    ) == [
        (1.0, 4.0),
        (5.0, 12.0),
    ]


def _naive_presence_mean(
    points: list[Point], interval: int, spans: list[tuple[int, int]], total: int
) -> tuple[float, int]:
    """Per-second reference: mark every second present, average the values there."""
    value_at = [0.0] * total
    for when, value in points:
        for second in range(int(when), int(when) + interval):
            value_at[second] = value
    present = [False] * total
    for start, end in spans:
        for second in range(start, end):
            present[second] = True
    seconds = [value_at[s] for s in range(total) if present[s]]
    return sum(seconds) / len(seconds), len(seconds)


@pytest.mark.parametrize("seed", range(12))
def test_influence_agrees_with_a_per_second_reference(seed: int) -> None:
    rng = random.Random(seed)
    interval = rng.choice([1, 5, 30, 60])
    count = rng.randint(2, 40)
    total = interval * count
    points = [(float(i * interval), float(rng.randint(0, 100))) for i in range(count)]
    spans_by_name: dict[str, list[tuple[int, int]]] = {}
    for number in range(rng.randint(1, 8)):
        spans = []
        for _ in range(rng.randint(1, 6)):
            start = rng.randint(0, total - 1)
            spans.append((start, min(total, start + rng.randint(1, total))))
        spans_by_name[f"e{number}"] = spans
    timeline = {
        "entities": [
            _entity(name, *[(float(a), float(b)) for a, b in spans])
            for name, spans in spans_by_name.items()
        ]
    }
    entries = _by_key(compute_influence(points, float(interval), timeline))
    overall = sum(value for _, value in points) / count
    assert set(entries) == {f"character:{name}" for name in spans_by_name}
    for name, spans in spans_by_name.items():
        entry = entries[f"character:{name}"]
        mean, seconds = _naive_presence_mean(points, interval, spans, total)
        assert entry["avg_during"] == pytest.approx(mean, abs=1e-4)
        assert entry["coverage_sec"] == seconds
        assert entry["coverage_pct"] == pytest.approx(100 * seconds / total, abs=0.01)
        if overall:
            expected = (mean - overall) / overall * 100
            assert entry["delta_pct"] == pytest.approx(expected, abs=0.01)


def test_keys_group_emotions_and_events_by_normalised_name() -> None:
    points = [(float(t), 50.0 + t) for t in range(0, 120, 5)]
    entries = _by_key(compute_influence(points, 5.0, _timeline()))
    assert set(entries) == {
        "location:kitchen",
        "character:asha",
        "character:judge",
        "object:trophy",
        "emotion:tension",
        "emotion:calm",
        "event:reveal",
    }
    tension = entries["emotion:tension"]
    assert tension["ref_id"] is None
    assert tension["name"] == "tension"
    assert tension["ranges"] == [{"start_sec": 0.0, "end_sec": 35.0}]  # 0-20 + 15-35
    assert entries["event:reveal"]["ranges"] == [
        {"start_sec": 40.0, "end_sec": 50.0},
        {"start_sec": 100.0, "end_sec": 110.0},
    ]
    assert entries["event:reveal"]["coverage_sec"] == 20.0
    assert entries["character:asha"]["ref_id"] == "ent-2"
    assert entries["location:kitchen"]["kind"] == "location"


def test_low_support_and_ordering() -> None:
    points = [(float(t), 50.0 + t) for t in range(0, 120, 5)]
    entries = compute_influence(points, 5.0, _timeline())
    flags = {entry["key"]: entry["low_support"] for entry in entries}
    assert flags["object:trophy"] is True  # on screen for 2 s
    assert sum(flags.values()) == 1
    supported = [e["delta_pct"] for e in entries if not e["low_support"]]
    assert supported == sorted(supported, reverse=True)
    assert entries[-1]["key"] == "object:trophy"
    # 4 s is under the 5 s absolute floor; 7 s of 400 s is under the 2% floor.
    short = compute_influence(
        [(float(t), 1.0) for t in range(40)],
        1.0,
        {"entities": [_entity("A", (0.0, 4.0))]},
    )
    long = compute_influence(
        [(float(t), 1.0) for t in range(400)],
        1.0,
        {"entities": [_entity("A", (0.0, 7.0)), _entity("B", (0.0, 9.0))]},
    )
    assert [e["low_support"] for e in short] == [True]
    assert {e["name"]: e["low_support"] for e in long} == {"A": True, "B": False}


def test_keys_outside_the_signal_are_dropped() -> None:
    timeline = {
        "entities": [
            _entity("Gone", (500.0, 600.0)),
            _entity("Edge", (100.0, 200.0)),
            _entity("Prop", (0.0, 60.0), kind="vehicle"),
            _entity("  ", (0.0, 60.0)),
        ]
    }
    entries = compute_influence(_MINUTES, 60.0, timeline)
    assert [entry["key"] for entry in entries] == ["character:edge"]
    assert entries[0]["coverage_sec"] == 20.0  # the signal ends at 120 s
    assert entries[0]["avg_during"] == 30.0
    assert compute_influence([], 60.0, timeline) == []


def test_zero_overall_mean_does_not_divide_by_zero() -> None:
    timeline = {"entities": [_entity("Asha", (0.0, 60.0))]}
    (flat,) = compute_influence([(0.0, 0.0), (60.0, 0.0)], 60.0, timeline)
    assert (flat["avg_during"], flat["delta_pct"]) == (0.0, 0.0)
    (signed,) = compute_influence([(0.0, -4.0), (60.0, 4.0)], 60.0, timeline)
    assert (signed["avg_during"], signed["delta_pct"]) == (-4.0, 0.0)
    stats = segment_stats(
        [(0.0, -4.0), (60.0, 4.0)],
        60.0,
        [{"id": "seg-1", "start_sec": 0, "end_sec": 60}],
    )
    assert stats == [{"segment_id": "seg-1", "avg": -4.0, "delta_pct": 0.0, "rank": 1}]


def test_segment_stats_are_time_weighted_and_ranked() -> None:
    segments = [
        {"id": "seg-1", "start_sec": 0.0, "end_sec": 30.0},
        {"id": "seg-2", "start_sec": 30.0, "end_sec": 90.0},
        {"id": "seg-3", "start_sec": 90.0, "end_sec": 120.0},
        {"id": "seg-4", "start_sec": 120.0, "end_sec": 150.0},  # after the signal
    ]
    assert segment_stats(_MINUTES, 60.0, segments) == [
        {"segment_id": "seg-1", "avg": 10.0, "delta_pct": -50.0, "rank": 3},
        {"segment_id": "seg-2", "avg": 20.0, "delta_pct": 0.0, "rank": 2},
        {"segment_id": "seg-3", "avg": 30.0, "delta_pct": 50.0, "rank": 1},
    ]
    tied = segment_stats([(0.0, 5.0), (60.0, 5.0)], 60.0, segments[:2])
    assert [s["rank"] for s in tied] == [1, 2]


def test_summary_stats_of_known_values() -> None:
    stats = summary_stats([(0.0, 4.0), (1.0, 1.0), (2.0, 3.0), (3.0, 2.0)])
    assert stats == {
        "avg": 2.5,
        "median": 2.5,
        "p75": 3.25,
        "min": 1.0,
        "max": 4.0,
        "std": round(math.sqrt(1.25), 4),
    }
    assert summary_stats([(0.0, 7.0)])["std"] == 0.0
    assert set(summary_stats([]).values()) == {0.0}


def test_integral_ignores_time_the_signal_does_not_cover() -> None:
    # Samples at 0 and 100 with a 10 s interval: 10-100 has no value.
    integral = SeriesIntegral([(0.0, 8.0), (100.0, 2.0)], 10.0)
    assert integral.total_cover == 20.0
    assert integral.overall_mean == 5.0
    assert integral.mean(5.0, 105.0) == 5.0  # 5 s at 8 and 5 s at 2
    assert integral.mean(20.0, 90.0) is None
    assert integral.over(-50.0, 4.0) == (32.0, 4.0)
    # Rows closer together than the interval do not overlap each other.
    crowded = SeriesIntegral([(0.0, 8.0), (4.0, 2.0)], 10.0)
    assert crowded.over(0.0, 100.0) == (8.0 * 4 + 2.0 * 10, 14.0)

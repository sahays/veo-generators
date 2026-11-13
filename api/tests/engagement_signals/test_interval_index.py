"""Interval index queries and timeline context slices."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from interval_index import IntervalIndex, TimelineIndex, context_slice

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "engagement_signals"
    / "timeline_small.json"
)
Span = tuple[float, float, int]


def _timeline() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _random_spans(rng: random.Random, count: int) -> list[Span]:
    """Mix of short spans, very long spans and instants on a 0..200 axis."""
    spans: list[Span] = []
    for ident in range(count):
        start = float(rng.randint(0, 200))
        shape = rng.random()
        length = (
            0.0 if shape < 0.2 else float(rng.randint(1, 150 if shape > 0.9 else 12))
        )
        spans.append((start, start + length, ident))
    return spans


def _naive_overlapping(spans: list[Span], start: float, end: float) -> list[int]:
    if end <= start:  # an empty window means "at this instant"
        return _naive_at(spans, start)
    hits = [
        span
        for span in spans
        if (span[0] < end and span[1] > start)
        or (span[0] == span[1] and start <= span[0] < end)
    ]
    return [span[2] for span in sorted(hits, key=lambda s: (s[0], s[1]))]


def _naive_at(spans: list[Span], when: float) -> list[int]:
    hits = [
        span
        for span in spans
        if span[0] <= when < span[1] or span[0] == span[1] == when
    ]
    return [span[2] for span in sorted(hits, key=lambda s: (s[0], s[1]))]


@pytest.mark.parametrize("seed", range(12))
def test_queries_agree_with_a_linear_scan_on_random_spans(seed: int) -> None:
    rng = random.Random(seed)
    spans = _random_spans(rng, rng.randint(0, 120))
    index = IntervalIndex.from_spans(spans)
    assert len(index) == len(spans)
    for _ in range(60):
        start = float(rng.randint(-5, 205))
        end = start + float(rng.choice([0, 1, 7, 40, 300]))
        assert sorted(index.overlapping(start, end)) == sorted(
            _naive_overlapping(spans, start, end)
        )
        assert sorted(index.at(start)) == sorted(_naive_at(spans, start))


def test_results_come_back_in_start_order() -> None:
    index = IntervalIndex.from_spans(
        [(30.0, 40.0, "c"), (0.0, 100.0, "a"), (10.0, 35.0, "b")]
    )
    assert index.overlapping(32.0, 33.0) == ["a", "b", "c"]
    assert index.at(36.0) == ["a", "c"]


def test_spans_are_half_open_and_instants_occupy_their_start() -> None:
    index = IntervalIndex.from_spans(
        [(0.0, 30.0, "first"), (30.0, 60.0, "second"), (30.0, 30.0, "moment")]
    )
    assert index.at(30.0) == ["moment", "second"]  # "first" ended at 30
    assert index.at(29.99) == ["first"]
    assert index.at(60.0) == []
    assert index.overlapping(20.0, 30.0) == ["first"]  # window end is exclusive
    assert index.overlapping(30.0, 31.0) == ["moment", "second"]
    assert index.overlapping(30.0, 30.0) == ["moment", "second"]
    assert index.overlapping(60.0, 90.0) == []
    assert IntervalIndex([]).overlapping(0.0, 10.0) == []


def test_one_long_span_does_not_hide_short_ones_that_already_ended() -> None:
    """A running max of ends would scan every span here; results must stay exact."""
    spans: list[tuple[float, float, str]] = [(0.0, 1000.0, "whole video")]
    spans += [(float(i), i + 0.5, f"cue-{i}") for i in range(1, 500)]
    index = IntervalIndex.from_spans(spans)
    assert index.overlapping(700.0, 701.0) == ["whole video"]
    assert index.overlapping(250.2, 251.2) == ["whole video", "cue-250", "cue-251"]


def test_dict_items_are_indexed_by_their_own_times() -> None:
    timeline = _timeline()
    moments = IntervalIndex(timeline["key_moments"])
    assert [m["id"] for m in moments.overlapping(40.0, 50.0)] == ["km-1"]
    assert moments.overlapping(45.5, 100.0) == []  # an instant has no length
    segments = IntervalIndex(timeline["segments"])
    assert [s["id"] for s in segments.overlapping(29.0, 61.0)] == [
        "seg-1",
        "seg-2",
        "seg-3",
    ]
    assert segments.at(45.0) == [timeline["segments"][1]]  # the item itself
    by_length = IntervalIndex(["bb", "a", "dddd"], span=lambda word: (0.0, len(word)))
    assert by_length.at(1.5) == ["bb", "dddd"]


def test_context_slice_contains_only_what_happens_inside_the_window() -> None:
    view = context_slice(_timeline(), 38.0, 52.0)
    assert set(view) == {
        "start_sec",
        "end_sec",
        "segments",
        "cues",
        "entities",
        "events",
        "emotions",
        "key_moments",
    }
    assert (view["start_sec"], view["end_sec"]) == (38.0, 52.0)
    assert view["segments"] == [
        {
            "id": "seg-2",
            "start_sec": 30.0,
            "end_sec": 60.0,
            "title": "The reveal",
            "synopsis": "The judge walks in early.",
        }
    ]
    assert [cue["text"] for cue in view["cues"]] == ["I hope I am not too early."]
    assert "id" not in view["cues"][0]
    assert view["entities"] == [
        {"name": "Kitchen", "kind": "location"},
        {"name": "Asha", "kind": "character"},
        {"name": "Judge", "kind": "character"},
    ]
    assert [event["tag"] for event in view["events"]] == ["reveal"]
    assert view["emotions"] == []
    assert view["key_moments"] == [
        {"start_sec": 45.0, "type": "twist", "label": "Judge arrives early"}
    ]


def test_context_slice_lists_each_entity_once_and_skips_absent_ones() -> None:
    index = TimelineIndex(_timeline())
    late = index.slice(92.0, 120.0)
    assert [e["name"] for e in late["entities"]] == ["Kitchen", "Judge", "Trophy"]
    whole = index.slice(0.0, 120.0)
    assert [e["name"] for e in whole["entities"]] == [
        "Kitchen",
        "Asha",
        "Judge",
        "Trophy",
    ]
    montage = index.slice(62.0, 88.0)
    assert montage["entities"] == []
    assert [e["emotion"] for e in montage["emotions"]] == ["calm"]
    assert index.segment_at(60.0)["id"] == "seg-3"
    assert index.segment_at(120.0) is None


def test_context_slice_stays_compact_for_busy_windows() -> None:
    timeline = _timeline()
    timeline["cues"] = [
        {
            "id": f"cue-{i}",
            "start_sec": float(i),
            "end_sec": i + 1.0,
            "text": "word " * 100,
            "kind": "dialogue",
            "speaker": "",
        }
        for i in range(100)
    ]
    view = context_slice(timeline, 0.0, 100.0)
    assert len(view["cues"]) <= 24
    starts = [cue["start_sec"] for cue in view["cues"]]
    assert starts[0] == 0.0
    assert starts[-1] >= 90.0  # thinned evenly, not truncated to the first few
    assert all(len(cue["text"]) == 240 for cue in view["cues"])
    assert all("speaker" not in cue for cue in view["cues"])

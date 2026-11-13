"""Binding LLM prose to the report: ids and keys are trusted, numbers never are."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from engagement_series import SignalSeries
from report_builder import (
    apply_explanations,
    apply_recommendations,
    build_report_core,
    recommendation_inputs,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "engagement_signals"
    / "timeline_small.json"
)
_METRIC = "Engagement index"


def _timeline() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _report() -> dict:
    """Signal at 50 with a bump to 80 at t=45 and a dip to 25 at t=75."""
    points = [
        (
            float(t),
            50.0
            + 30.0 * math.exp(-(((t - 45.0) / 8.0) ** 2))
            - 25.0 * math.exp(-(((t - 75.0) / 8.0) ** 2)),
        )
        for t in range(0, 120, 5)
    ]
    series = SignalSeries({_METRIC: points}, _METRIC, 5.0, 120.0)
    return build_report_core(_timeline(), series, {"kind": "template"})


def _influence(report: dict, key: str) -> dict:
    return next(entry for entry in report["influence"] if entry["key"] == key)


def test_explanations_bind_by_id_and_cannot_change_numbers() -> None:
    report = _report()
    items = [
        {
            "id": "peak-1",
            "title": "  The judge walks in  ",
            "explanation": "Viewers lean in at the reveal.",
            "drivers": ["Judge", "reveal", "", 7],
            "time_sec": 1.0,
            "value": 999.0,
            "delta_pct": 500.0,
            "segment_id": "seg-9",
            "kind": "valley",
        },
        {"id": "peak-77", "title": "Invented", "explanation": "Not in the report."},
        {"id": "peak-1", "title": "Second copy", "explanation": "Ignored."},
    ]
    bound = apply_explanations(report, items)
    by_id = {extremum["id"]: extremum for extremum in bound["extrema"]}
    assert list(by_id) == [extremum["id"] for extremum in report["extrema"]]
    original = report["extrema"][0]
    assert by_id["peak-1"] == {
        **original,
        "title": "The judge walks in",
        "explanation": "Viewers lean in at the reveal.",
        "drivers": ["Judge", "reveal"],
    }
    assert (by_id["peak-1"]["value"], by_id["peak-1"]["kind"]) == (80.0, "peak")
    # No item for the valley or the drops: they keep empty prose.
    assert by_id["valley-1"] == report["extrema"][1]
    assert by_id["drop-1"]["title"] == ""
    assert {key: bound[key] for key in bound if key != "extrema"} == {
        key: report[key] for key in report if key != "extrema"
    }


def test_explanations_tolerate_malformed_model_output() -> None:
    report = _report()
    junk: list[Any] = [
        "peak-1",
        None,
        {"title": "No id"},
        {"id": 3, "title": "Numeric id"},
        {"id": "valley-1", "title": 12, "explanation": None, "drivers": "Judge"},
    ]
    bound = apply_explanations(report, junk)
    valley = bound["extrema"][1]
    assert (valley["title"], valley["explanation"], valley["drivers"]) == ("", "", [])
    assert bound["extrema"][0] == report["extrema"][0]
    assert apply_explanations(report, [])["extrema"] == report["extrema"]


def test_explanations_return_a_new_report() -> None:
    report = _report()
    snapshot = copy.deepcopy(report)
    bound = apply_explanations(
        report, [{"id": "peak-1", "title": "T", "explanation": "E", "drivers": ["D"]}]
    )
    bound["extrema"][0]["window"]["start_sec"] = -1.0
    bound["extrema"][0]["drivers"].append("mutated")
    assert report == snapshot
    assert bound is not report


def test_recommendation_inputs_use_supported_influence_and_ranked_segments() -> None:
    timeline = _timeline()
    report = _report()
    inputs = recommendation_inputs(report, timeline)
    assert set(inputs) == {
        "content_title",
        "summary",
        "duration_sec",
        "signal",
        "stats",
        "top_influence",
        "bottom_influence",
        "high_segments",
        "low_segments",
    }
    assert inputs["content_title"] == "Cook-off"
    assert inputs["stats"] == report["stats"]
    assert inputs["signal"]["simulated"] is True
    top = [entry["key"] for entry in inputs["top_influence"]]
    bottom = [entry["key"] for entry in inputs["bottom_influence"]]
    assert top[0] == "event:reveal"
    assert set(top) == {
        "event:reveal",
        "character:judge",
        "character:asha",
        "location:kitchen",
    }
    assert bottom[0] == "emotion:calm"
    assert "object:trophy" not in top + bottom  # 2 s on screen: low support
    assert _influence(report, "object:trophy")["low_support"] is True
    deltas = [entry["delta_pct"] for entry in inputs["top_influence"]]
    assert deltas == sorted(deltas, reverse=True)
    assert all(delta > 0 for delta in deltas)
    assert all(entry["delta_pct"] < 0 for entry in inputs["bottom_influence"])
    assert "ranges" not in inputs["top_influence"][0]
    assert (
        inputs["top_influence"][0]["delta_pct"]
        == _influence(report, "event:reveal")["delta_pct"]
    )
    high, low = inputs["high_segments"], inputs["low_segments"]
    assert [segment["segment_id"] for segment in high] == ["seg-2"]
    assert low[0]["segment_id"] == "seg-3"
    assert low[0] == {
        "segment_id": "seg-3",
        "title": "Prep montage",
        "synopsis": "Chopping and plating without dialogue.",
        "start_sec": 60.0,
        "end_sec": 90.0,
        "avg": report["segments"][2]["avg"],
        "delta_pct": report["segments"][2]["delta_pct"],
        "rank": 4,
    }
    assert not {s["segment_id"] for s in high} & {s["segment_id"] for s in low}


def test_recommendation_evidence_is_filled_from_the_report() -> None:
    report = _report()
    reveal = _influence(report, "event:reveal")
    payload = {
        "headline": " Lead with the reveal. ",
        "do_more": [
            {
                "title": "Bring reveals forward",
                "rationale": "Reveals coincide with the highest engagement.",
                "expected_lift": "high",
                "key": "event:reveal",
                "delta_pct": 900.0,
                "coverage_sec": 1.0,
                "name": "Something else",
                "anchor_times": [1.0],
            },
            {"title": "Cite nested", "evidence": {"key": "character:judge"}},
            {"title": "General advice", "rationale": "No evidence cited."},
        ],
        "do_less": [
            {
                "title": "Trim the montage",
                "evidence_key": "emotion:calm",
                "expected_lift": "huge",
            },
            {"title": "Invented", "key": "character:nobody", "expected_lift": "high"},
            {"rationale": "No title", "key": "emotion:calm"},
        ],
    }
    bound = apply_recommendations(report, payload, _timeline())["recommendations"]
    assert bound["headline"] == "Lead with the reveal."
    assert bound["segment_fixes"] == []
    assert [item["title"] for item in bound["do_more"]] == [
        "Bring reveals forward",
        "Cite nested",
        "General advice",
    ]
    assert bound["do_more"][0] == {
        "title": "Bring reveals forward",
        "rationale": "Reveals coincide with the highest engagement.",
        "expected_lift": "high",
        "evidence": {
            "key": "event:reveal",
            "name": "reveal",
            "kind": "event",
            "delta_pct": reveal["delta_pct"],
            "coverage_sec": 20.0,
            "anchor_times": [40.0, 100.0],
        },
    }
    assert bound["do_more"][1]["evidence"]["name"] == "Judge"
    assert bound["do_more"][1]["expected_lift"] == "low"
    assert bound["do_more"][2]["evidence"] is None
    # Unknown key and missing title are dropped; an invalid lift is downgraded.
    assert [item["title"] for item in bound["do_less"]] == ["Trim the montage"]
    assert bound["do_less"][0]["expected_lift"] == "low"
    assert bound["do_less"][0]["evidence"]["delta_pct"] < 0


def test_segment_fixes_take_times_from_the_timeline_and_avg_from_the_report() -> None:
    report = _report()
    payload = {
        "segment_fixes": [
            {
                "segment_id": "seg-3",
                "what_happened": "A silent montage.",
                "why_low": "Nothing is at stake.",
                "fix": "Intercut the judge's reactions.",
                "start_sec": 0.0,
                "end_sec": 5.0,
                "avg": 99.0,
            },
            {"segment_id": "seg-42", "fix": "Unknown segment."},
            {"segment_id": "seg-3", "fix": "Repeated segment."},
            {"segment_id": "seg-1"},
            {"fix": "No segment."},
        ]
    }
    bound = apply_recommendations(report, payload, _timeline())["recommendations"]
    assert bound["segment_fixes"] == [
        {
            "segment_id": "seg-3",
            "start_sec": 60.0,
            "end_sec": 90.0,
            "avg": report["segments"][2]["avg"],
            "what_happened": "A silent montage.",
            "why_low": "Nothing is at stake.",
            "fix": "Intercut the judge's reactions.",
        }
    ]
    assert bound["segment_fixes"][0]["avg"] < report["stats"]["avg"]
    # A segment must be known to both the timeline and the report's statistics.
    fix = {"segment_fixes": [{"segment_id": "seg-3", "fix": "Tighten it."}]}
    shorter = {**_timeline(), "segments": _timeline()["segments"][:2]}
    assert (
        apply_recommendations(report, fix, shorter)["recommendations"]["segment_fixes"]
        == []
    )
    unmeasured = {**report, "segments": report["segments"][:2]}
    assert (
        apply_recommendations(unmeasured, fix, _timeline())["recommendations"][
            "segment_fixes"
        ]
        == []
    )
    assert (bound["headline"], bound["do_more"], bound["do_less"]) == ("", [], [])


def test_anchor_times_are_the_starts_of_the_longest_ranges() -> None:
    report = _report()
    busy = {
        **_influence(report, "event:reveal"),
        "key": "event:busy",
        "ranges": [
            {"start_sec": float(10 * i), "end_sec": 10.0 * i + length}
            for i, length in enumerate([1, 6, 2, 7, 3, 8, 4, 9, 5])
        ],
    }
    report = {**report, "influence": [*report["influence"], busy]}
    payload = {"do_more": [{"title": "Use it", "key": "event:busy"}]}
    bound = apply_recommendations(report, payload, _timeline())["recommendations"]
    assert bound["do_more"][0]["evidence"]["anchor_times"] == [
        10.0,
        30.0,
        50.0,
        70.0,
        80.0,
    ]


def test_recommendations_return_a_new_report_and_survive_junk_payloads() -> None:
    report = _report()
    snapshot = copy.deepcopy(report)
    timeline = _timeline()
    bound = apply_recommendations(
        report, {"do_more": [{"title": "T", "key": "event:reveal"}]}, timeline
    )
    bound["recommendations"]["do_more"][0]["evidence"]["anchor_times"].append(-1.0)
    assert report == snapshot
    assert report["recommendations"]["do_more"] == []
    empty = {"headline": "", "do_more": [], "do_less": [], "segment_fixes": []}
    junk_payloads: list[Any] = [
        None,
        [],
        {"do_more": "x", "do_less": [1, None], "segment_fixes": {}, "headline": 5},
    ]
    for payload in junk_payloads:
        assert (
            apply_recommendations(report, payload, timeline)["recommendations"] == empty
        )

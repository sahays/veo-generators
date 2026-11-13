"""Cross-window merge: order independence, dedupe, entity fusion, ids, clamping."""

from __future__ import annotations

import itertools
import json
from typing import Any

from timeline_merge import (
    combine_window_parts,
    merge_windows,
    normalize_window_result,
    timeline_counts,
)
from timeline_windows import Window

DURATION = 1500.0
CUTS = [498.9, 1000.0, 250.0]
WINDOWS = [Window(0, 0.0, 500.0), Window(1, 500.0, 1000.0), Window(2, 1000.0, 1500.0)]


def _window_raw(window: Window, hero: str, title: str = "") -> dict[str, Any]:
    """Raw model output for one window, in absolute seconds."""
    s, e = window.start_sec, window.end_sec
    return {
        "summary": f"Part {window.index + 1}.",
        "content_title": title,
        "segments": [
            {"start_sec": s, "end_sec": s + 250, "title": f"Scene {window.index}a"},
            {"start_sec": s + 250, "end_sec": e, "title": f"Scene {window.index}b"},
        ],
        "cues": [
            {
                "start_sec": s + 10,
                "end_sec": s + 14,
                "text": "Hello",
                "kind": "dialogue",
            },
            {
                "start_sec": s + 10,
                "end_sec": s + 14,
                "text": "Hello",
                "kind": "dialogue",
            },
            {
                "start_sec": s + 30,
                "end_sec": s + 31,
                "text": "[door slams]",
                "kind": "sfx",
            },
        ],
        "entities": [
            {
                "name": hero,
                "kind": "character",
                "description": "The lead"
                if window.index
                else "The lead, in a red coat",
                "appearances": [
                    {"start_sec": s + 400, "end_sec": e},
                    {"start_sec": s, "end_sec": s + 100},
                ],
            },
            {
                "name": "Market",
                "kind": "location",
                "appearances": [{"start_sec": s + 50, "end_sec": s + 60}],
            },
        ],
        "events": [{"start_sec": s + 5, "end_sec": s + 45, "tag": "action"}],
        "emotions": [
            {"start_sec": s, "end_sec": s + 50, "emotion": "joy", "intensity": 0.2},
            {
                "start_sec": s + 20,
                "end_sec": s + 50,
                "emotion": "joy",
                "intensity": 0.9,
            },
        ],
        "key_moments": [{"start_sec": s + 45, "type": "reveal", "label": "Twist"}],
        "narrative_beats": [{"start_sec": s, "end_sec": e, "beat": "rising_action"}],
        "ad_opportunities": [
            {
                "start_sec": s + 60,
                "end_sec": s + 75,
                "placement_type": "virtual_placement",
                "surface_or_trigger": "Tabletop",
                "suggested_category": "Beverages",
                "rationale": "Clear surface with low clutter.",
                "suitability": 0.85,
            }
        ],
    }


def _results() -> list[dict[str, Any]]:
    heroes = ["Ravi", "  ravi ", "RAVI."]
    titles = ["", "Market Run", "Another Title"]
    return [
        normalize_window_result(_window_raw(w, heroes[w.index], titles[w.index]), w)
        for w in WINDOWS
    ]


def test_merge_is_identical_for_every_window_completion_order() -> None:
    results = _results()
    expected = json.dumps(merge_windows(results, DURATION, CUTS), sort_keys=True)
    for order in itertools.permutations(results):
        merged = merge_windows(list(order), DURATION, list(reversed(CUTS)))
        assert json.dumps(merged, sort_keys=True) == expected


def test_summary_and_title_follow_video_order_not_arrival_order() -> None:
    timeline = merge_windows(list(reversed(_results())), DURATION, CUTS)
    assert timeline["summary"] == "Part 1. Part 2. Part 3."
    assert timeline["content_title"] == "Market Run"
    assert timeline["schema_version"] == "video-timeline-v1"
    assert timeline["cuts"] == [250.0, 498.9, 1000.0]


def test_duplicate_items_are_removed() -> None:
    timeline = merge_windows(_results(), DURATION, CUTS)
    hellos = [c for c in timeline["cues"] if c["text"] == "Hello"]
    assert [c["start_sec"] for c in hellos] == [10.0, 510.0, 1010.0]
    assert timeline_counts(timeline)["cues"] == 6


def test_entity_is_merged_across_windows_by_normalised_name_and_kind() -> None:
    timeline = merge_windows(_results(), DURATION, CUTS)
    heroes = [e for e in timeline["entities"] if e["kind"] == "character"]
    assert len(heroes) == 1
    hero = heroes[0]
    # "Ravi", "  ravi " and "RAVI." are one entity. Its appearance that runs up
    # to a window boundary fuses with the one that starts on it.
    assert hero["appearances"] == [
        {"start_sec": 0.0, "end_sec": 100.0},
        {"start_sec": 400.0, "end_sec": 600.0},
        {"start_sec": 900.0, "end_sec": 1100.0},
        {"start_sec": 1400.0, "end_sec": 1500.0},
    ]
    assert hero["screen_time_sec"] == 600.0
    assert hero["description"] == "The lead, in a red coat"


def test_same_name_with_a_different_kind_stays_a_separate_entity() -> None:
    results = _results()
    results[0]["entities"].append(
        {
            "name": "Ravi",
            "kind": "location",
            "appearances": [{"start_sec": 1.0, "end_sec": 2.0}],
        }
    )
    timeline = merge_windows(results, DURATION, CUTS)
    kinds = sorted(
        e["kind"] for e in timeline["entities"] if "ravi" in e["name"].lower()
    )
    assert kinds == ["character", "location"]


def test_overlapping_appearances_are_fused_before_screen_time_is_summed() -> None:
    window = Window(0, 0.0, 100.0)
    raw = {
        "entities": [
            {
                "name": "Dog",
                "kind": "character",
                "appearances": [
                    {"start_sec": 10, "end_sec": 30},
                    {"start_sec": 20, "end_sec": 40},
                    {"start_sec": 40.03, "end_sec": 50},
                    {"start_sec": 70, "end_sec": 80},
                ],
            }
        ]
    }
    timeline = merge_windows([normalize_window_result(raw, window)], 100.0, [])
    dog = timeline["entities"][0]
    assert dog["appearances"] == [
        {"start_sec": 10.0, "end_sec": 50.0},
        {"start_sec": 70.0, "end_sec": 80.0},
    ]
    assert dog["screen_time_sec"] == 50.0


def test_ids_are_one_based_in_start_order_and_entities_rank_by_screen_time() -> None:
    timeline = merge_windows(list(reversed(_results())), DURATION, CUTS)
    prefixes = {
        "segments": "seg",
        "cues": "cue",
        "events": "evt",
        "emotions": "emo",
        "key_moments": "km",
        "narrative_beats": "nb",
        "ad_opportunities": "ad",
    }
    for name, prefix in prefixes.items():
        items = timeline[name]
        assert [i["id"] for i in items] == [
            f"{prefix}-{n}" for n in range(1, len(items) + 1)
        ]
        starts = [i["start_sec"] for i in items]
        assert starts == sorted(starts)
    entities = timeline["entities"]
    assert [e["id"] for e in entities] == ["ent-1", "ent-2"]
    # Three spellings, one vote each: the earliest in the video wins.
    assert [e["name"] for e in entities] == ["Ravi", "Market"]
    assert entities[0]["screen_time_sec"] > entities[1]["screen_time_sec"]


def test_times_are_clamped_to_the_video_duration() -> None:
    # The probe said 1500 s but the last window was normalised against 1510.
    late = normalize_window_result(
        {
            "segments": [{"start_sec": 1000, "end_sec": 1510, "title": "Finale"}],
            "cues": [
                {"start_sec": 1499, "end_sec": 1508, "text": "Bye", "kind": "dialogue"},
                {
                    "start_sec": 1502,
                    "end_sec": 1508,
                    "text": "Late",
                    "kind": "dialogue",
                },
            ],
            "key_moments": [{"start_sec": 1500.6, "type": "hook", "label": "End"}],
        },
        Window(2, 1000.0, 1510.0),
    )
    timeline = merge_windows([late], DURATION, [])
    assert timeline["duration_sec"] == 1500.0
    assert timeline["segments"][0]["end_sec"] == 1500.0
    assert [(c["text"], c["end_sec"]) for c in timeline["cues"]] == [("Bye", 1500.0)]
    assert timeline["key_moments"][0]["start_sec"] == 1500.0


def test_segments_snap_to_cuts_and_form_a_partition() -> None:
    window = Window(0, 0.0, 100.0)
    raw = {
        "segments": [
            {"start_sec": 0.6, "end_sec": 30.4, "title": "one"},  # 30.4 -> cut 30.0
            {"start_sec": 29.8, "end_sec": 55.0, "title": "two"},  # overlaps "one"
            {"start_sec": 55.7, "end_sec": 70.0, "title": "three"},  # 0.7 s gap
            {"start_sec": 80.0, "end_sec": 99.5, "title": "four"},  # 10 s gap stays
        ]
    }
    timeline = merge_windows([normalize_window_result(raw, window)], 100.0, [30.0])
    assert [
        (s["title"], s["start_sec"], s["end_sec"]) for s in timeline["segments"]
    ] == [
        ("one", 0.0, 30.0),
        ("two", 30.0, 55.7),
        ("three", 55.7, 70.0),
        ("four", 80.0, 100.0),
    ]


def test_emotion_intensity_is_kept_per_span() -> None:
    timeline = merge_windows(_results()[:1], 500.0, [])
    joy = [(e["start_sec"], e["end_sec"], e["intensity"]) for e in timeline["emotions"]]
    assert joy == [(0.0, 50.0, 0.2), (20.0, 50.0, 0.9)]


def test_split_window_parts_merge_like_the_unsplit_window() -> None:
    parent = WINDOWS[1]
    halves = [Window(1, 500.0, 750.0), Window(1, 750.0, 1000.0)]
    raw = _window_raw(parent, "Ravi")
    parts = [normalize_window_result(raw, half) for half in halves]
    combined = combine_window_parts(list(reversed(parts)), parent)
    assert combined["window"] == {"index": 1, "start_sec": 500.0, "end_sec": 1000.0}
    whole = merge_windows([normalize_window_result(raw, parent)], DURATION, CUTS)
    rejoined = merge_windows([combined], DURATION, CUTS)
    # Splitting may cut an item in two at 750 but must not lose or move footage.
    for name in ("cues", "events", "key_moments", "entities"):
        assert rejoined[name] == whole[name]
    assert rejoined["segments"][0]["start_sec"] == whole["segments"][0]["start_sec"]
    assert rejoined["segments"][-1]["end_sec"] == whole["segments"][-1]["end_sec"]


def test_counts_cover_every_collection() -> None:
    counts = timeline_counts(merge_windows(_results(), DURATION, CUTS))
    assert counts == {
        "segments": 6,
        "cues": 6,
        "events": 3,
        "emotions": 6,
        "key_moments": 3,
        "narrative_beats": 3,
        "ad_opportunities": 3,
        "entities": 2,
        "cuts": 3,
    }

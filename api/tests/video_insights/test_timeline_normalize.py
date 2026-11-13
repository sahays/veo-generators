"""Per-window normalisation: time base detection, clamping and item hygiene."""

from __future__ import annotations

from typing import Any

from timeline_merge import normalize_window_result
from timeline_windows import Window

WINDOW = Window(1, 600.0, 1200.0)


def _raw(offset: float) -> dict[str, Any]:
    """A plausible model answer for WINDOW with every time shifted by `offset`.

    `offset=600` gives absolute timestamps, `offset=0` window-relative ones.
    """
    return {
        "summary": "  A chase   through the market. ",
        "content_title": "Market Run",
        "segments": [
            {"start_sec": offset, "end_sec": offset + 300, "title": "Chase"},
            {"start_sec": offset + 300, "end_sec": offset + 600, "title": "Escape"},
        ],
        "cues": [
            {
                "start_sec": offset + 12.345,
                "end_sec": offset + 15.678,
                "text": "Stop him!",
                "kind": "dialogue",
                "speaker": "Guard",
            }
        ],
        "entities": [
            {
                "name": "Ravi",
                "kind": "character",
                "appearances": [{"start_sec": offset + 5, "end_sec": offset + 580}],
            }
        ],
        "events": [{"start_sec": offset + 20, "end_sec": offset + 90, "tag": "action"}],
        "emotions": [
            {
                "start_sec": offset + 20,
                "end_sec": offset + 90,
                "emotion": "tension",
                "intensity": 0.8,
            }
        ],
        "key_moments": [{"start_sec": offset + 300, "type": "twist", "label": "Trap"}],
    }


def _times(result: dict[str, Any]) -> list[float]:
    return [
        result["segments"][0]["start_sec"],
        result["segments"][1]["end_sec"],
        result["cues"][0]["start_sec"],
        result["cues"][0]["end_sec"],
        result["entities"][0]["appearances"][0]["start_sec"],
        result["key_moments"][0]["start_sec"],
    ]


def test_absolute_timestamps_are_kept_as_they_are() -> None:
    result = normalize_window_result(_raw(600.0), WINDOW)
    assert result["time_base"] == "absolute"
    assert _times(result) == [600.0, 1200.0, 612.35, 615.68, 605.0, 900.0]


def test_window_relative_timestamps_are_shifted_to_absolute() -> None:
    result = normalize_window_result(_raw(0.0), WINDOW)
    assert result["time_base"] == "relative"
    assert _times(result) == [600.0, 1200.0, 612.35, 615.68, 605.0, 900.0]


def test_both_time_bases_normalise_to_the_same_result() -> None:
    absolute = normalize_window_result(_raw(600.0), WINDOW)
    relative = normalize_window_result(_raw(0.0), WINDOW)
    absolute.pop("time_base")
    relative.pop("time_base")
    assert absolute == relative


def test_ambiguous_overlap_tie_is_read_as_absolute() -> None:
    # Window 100..400 (length 300): every timestamp in 100..300 is inside the
    # window both as an absolute time and as a window-relative one.
    window = Window(1, 100.0, 400.0)
    raw = {
        "segments": [{"start_sec": 120, "end_sec": 200, "title": "A"}],
        "cues": [{"start_sec": 210, "end_sec": 290, "text": "Hi", "kind": "dialogue"}],
    }
    result = normalize_window_result(raw, window)
    assert result["time_base"] == "absolute"
    assert result["segments"][0]["start_sec"] == 120.0
    assert result["cues"][0]["end_sec"] == 290.0


def test_one_vote_breaks_the_overlap_tie_towards_relative() -> None:
    # Same overlap as above plus one timestamp (40) that only fits as relative.
    window = Window(1, 100.0, 400.0)
    raw = {
        "segments": [{"start_sec": 40, "end_sec": 200, "title": "A"}],
        "cues": [{"start_sec": 210, "end_sec": 290, "text": "Hi", "kind": "dialogue"}],
    }
    result = normalize_window_result(raw, window)
    assert result["time_base"] == "relative"
    assert (result["segments"][0]["start_sec"], result["segments"][0]["end_sec"]) == (
        140.0,
        300.0,
    )


def test_first_window_is_never_shifted() -> None:
    window = Window(0, 0.0, 600.0)
    result = normalize_window_result(_raw(0.0), window)
    assert result["time_base"] == "absolute"
    assert result["cues"][0]["start_sec"] == 12.35


def test_minority_items_on_the_other_time_base_cannot_escape_the_window() -> None:
    raw = _raw(0.0)  # relative majority
    raw["events"].append({"start_sec": 650, "end_sec": 700, "tag": "music"})
    result = normalize_window_result(raw, WINDOW)
    assert result["time_base"] == "relative"
    # The stray absolute event becomes 1250..1300, outside the window: dropped.
    assert [e["tag"] for e in result["events"]] == ["action"]


def test_ranges_are_clamped_to_the_window_and_bad_ranges_dropped() -> None:
    raw = {
        "segments": [
            {"start_sec": 590, "end_sec": 640, "title": "starts early"},
            {"start_sec": 1190, "end_sec": 1260, "title": "ends late"},
            {"start_sec": 800, "end_sec": 700, "title": "inverted"},
            {"start_sec": 900, "end_sec": 900, "title": "empty"},
            {"start_sec": "n/a", "end_sec": 950, "title": "not a number"},
            {"start_sec": 1300, "end_sec": 1400, "title": "outside"},
            {"start_sec": True, "end_sec": 950, "title": "boolean"},
            "not an object",
        ]
    }
    result = normalize_window_result(raw, WINDOW)
    assert [(s["title"], s["start_sec"], s["end_sec"]) for s in result["segments"]] == [
        ("starts early", 600.0, 640.0),
        ("ends late", 1190.0, 1200.0),
    ]


def test_key_moments_far_outside_are_dropped_and_near_ones_pulled_in() -> None:
    raw = {
        "segments": [{"start_sec": 600, "end_sec": 1200, "title": "all"}],
        "key_moments": [
            {"start_sec": 599.6, "type": "hook", "label": "just before"},
            {"start_sec": 1200.9, "type": "reveal", "label": "just after"},
            {"start_sec": 1300, "type": "twist", "label": "far after"},
            {"start_sec": 900, "type": "", "label": "no type"},
        ],
    }
    result = normalize_window_result(raw, WINDOW)
    assert [(k["label"], k["start_sec"]) for k in result["key_moments"]] == [
        ("just before", 600.0),
        ("just after", 1200.0),
    ]


def test_items_without_identifying_text_are_dropped_and_fields_tidied() -> None:
    raw = {
        "cues": [
            {"start_sec": 610, "end_sec": 612, "text": "   ", "kind": "dialogue"},
            {"start_sec": 620, "end_sec": 622, "text": "Run!", "speaker": ""},
        ],
        "events": [
            {"start_sec": 630, "end_sec": 640, "tag": "fight", "intensity": 7},
            {"start_sec": 650, "end_sec": 660, "tag": "music"},
        ],
        "emotions": [
            {"start_sec": 630, "end_sec": 640, "emotion": "fear", "intensity": -2},
            {"start_sec": 650, "end_sec": 660, "emotion": "calm"},
        ],
    }
    result = normalize_window_result(raw, WINDOW)
    # Missing kind falls back to dialogue; the empty optional speaker is omitted.
    assert result["cues"] == [
        {"start_sec": 620.0, "end_sec": 622.0, "text": "Run!", "kind": "dialogue"}
    ]
    assert [e.get("intensity") for e in result["events"]] == [1.0, None]
    assert "intensity" not in result["events"][1]
    assert [e["intensity"] for e in result["emotions"]] == [0.0, 0.5]


def test_entities_need_a_name_and_at_least_one_valid_appearance() -> None:
    raw = {
        "entities": [
            {"name": "Ghost", "kind": "character", "appearances": []},
            {
                "name": "",
                "kind": "object",
                "appearances": [{"start_sec": 700, "end_sec": 710}],
            },
            {
                "name": "Lamp",
                "kind": "object",
                "description": "A brass lamp",
                "appearances": [
                    {"start_sec": 700, "end_sec": 710},
                    {"start_sec": 720, "end_sec": 715},
                    {"start_sec": 1195, "end_sec": 1230},
                ],
            },
        ]
    }
    result = normalize_window_result(raw, WINDOW)
    assert result["entities"] == [
        {
            "name": "Lamp",
            "kind": "object",
            "description": "A brass lamp",
            "appearances": [
                {"start_sec": 700.0, "end_sec": 710.0},
                {"start_sec": 1195.0, "end_sec": 1200.0},
            ],
        }
    ]


def test_malformed_model_output_normalises_to_an_empty_result() -> None:
    for raw in (None, [], "text", {"segments": "oops", "entities": {"name": "x"}}):
        result = normalize_window_result(raw, WINDOW)  # type: ignore[arg-type]
        assert result["window"] == {"index": 1, "start_sec": 600.0, "end_sec": 1200.0}
        assert result["segments"] == [] and result["entities"] == []
        assert result["summary"] == ""


def test_summary_and_title_whitespace_is_collapsed() -> None:
    result = normalize_window_result(_raw(600.0), WINDOW)
    assert result["summary"] == "A chase through the market."
    assert result["content_title"] == "Market Run"

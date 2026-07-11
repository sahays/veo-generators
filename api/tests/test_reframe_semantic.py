"""Whole-video semantic pass (Phase 4): prompt contract, validation/binding,
the two-key letterbox lock, planner branches, and the fallback ladder.

The structural invariants pinned here are the ones that killed the retired
dense pass (commit 0d57d70): no coverage floats, no coordinates from Gemini,
scenes=[] must reproduce legacy behavior exactly.
"""

import json
from pathlib import Path

from ai_helpers import load_schema
from reframe_plan import RUNGS, collect_escalation_points, reconcile
from reframe_semantic import (
    _text_keep,
    build_semantic_prompt,
    reconcile_semantics,
    semantic_pass_enabled,
    validate,
)

SRC_W, SRC_H = 1920, 1080


def _frame(t, tracks):
    return {"time_sec": t, "tracks": tracks}


def _tr(tid, x, w=0.1, conf=0.9):
    return {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": conf}


def _shot(start, end, kind, **kw):
    return {"start_sec": start, "end_sec": end, "content_kind": kind, **kw}


# ---------------------------------------------------------------------------
# Schema + prompt contract
# ---------------------------------------------------------------------------
def test_schema_has_no_coverage_or_coordinates():
    # The dense-pass failure mode must be structurally impossible: nothing in
    # the schema lets the model emit a number that could reach crop math.
    raw = (
        Path(__file__).parent.parent / "schemas" / "reframe-semantic-schema.json"
    ).read_text()
    assert "coverage" not in raw
    assert "min_horizontal" not in raw and "requires_full_width" not in raw
    schema = load_schema("reframe-semantic-schema")
    assert schema["required"] == ["shots"]


def test_prompt_carries_cuts_chirp_and_importance_framing():
    prompt = build_semantic_prompt([3.0, 7.5], "=== SPEAKERS ===\nS1 ...", 12.0)
    assert "3.00s" in prompt and "7.50s" in prompt
    assert "S1" in prompt
    assert "IMPORTANCE, NOT READABILITY" in prompt
    assert "never" in prompt.lower() and "pixel coordinates" in prompt
    # offscreen narration guidance (the poster-hijack class)
    assert "offscreen" in prompt


# ---------------------------------------------------------------------------
# validate(): binding + garbage handling
# ---------------------------------------------------------------------------
def test_validate_snaps_to_cuts_and_drops_garbage():
    cuts = [4.0, 8.0]
    payload = {
        "shots": [
            _shot(0.2, 3.8, "talking_head"),  # snaps to 0.0-4.0
            _shot(4.1, 8.3, "montage"),  # snaps to 4.0-8.0
            _shot(7.9, 12.0, "bad_kind"),  # invalid enum → dropped
            _shot(8.0, 12.0, "broll_scenery"),
        ]
    }
    shots = validate(payload, cuts, 12.0)
    assert [(s["start_sec"], s["end_sec"]) for s in shots] == [
        (0.0, 4.0),
        (4.0, 8.0),
        (8.0, 12.0),
    ]


def test_validate_rejects_unusable_payloads():
    assert validate({}, [], 10.0) is None
    assert validate({"shots": []}, [], 10.0) is None
    assert validate({"shots": "garbage"}, [], 10.0) is None
    # Coverage below the floor (one 1s shot of a 30s video) → unusable.
    assert validate({"shots": [_shot(0, 1, "action")]}, [], 30.0) is None


def test_validate_drops_overlapping_shots_keeps_earlier():
    shots = validate(
        {
            "shots": [
                _shot(0, 6, "talking_head"),
                _shot(2, 9, "action"),  # overlaps the first by >tol → dropped
                _shot(6, 10, "broll_scenery"),
            ]
        },
        [6.0],
        10.0,
    )
    assert [(s["start_sec"], s["end_sec"]) for s in shots] == [(0.0, 6.0), (6.0, 10.0)]


# ---------------------------------------------------------------------------
# _text_keep: the two-key lock
# ---------------------------------------------------------------------------
CAPTION_REGION = {
    "box": [0.15, 0.8, 0.85, 0.86],
    "times": [1.0, 1.5, 2.0],
    "video_frac": 0.2,
    "kind": "candidate",
}


def test_essential_text_with_measured_region_uses_measured_band():
    shot = _shot(
        0,
        3,
        "talking_head",
        text_elements=[
            {
                "kind": "lower_third_caption",
                "importance": "essential",
                "extent": "full_width",
            }
        ],
    )
    tk = _text_keep(shot, [CAPTION_REGION])
    assert tk["low_confidence"] is False
    assert tk["band"] == [0.15, 0.85]  # geometry wins over the coarse extent


def test_essential_text_with_no_measured_region_falls_back_to_prior():
    shot = _shot(
        0,
        3,
        "title_card",
        text_elements=[
            {"kind": "title", "importance": "essential", "extent": "center_third"}
        ],
    )
    tk = _text_keep(shot, [])
    assert tk["low_confidence"] is True
    assert tk["band"] == [0.31, 0.69]


def test_incidental_or_watermark_text_never_locks():
    shot = _shot(
        0,
        3,
        "talking_head",
        text_elements=[
            {"kind": "watermark_bug", "importance": "essential", "extent": "corner"},
            {"kind": "callout", "importance": "incidental", "extent": "left_half"},
        ],
    )
    # Even with a measured band present, no semantic key → no lock → crop.
    assert _text_keep(shot, [CAPTION_REGION]) is None


# ---------------------------------------------------------------------------
# Planner branches
# ---------------------------------------------------------------------------
def _scenes(*shots, regions=None):
    return reconcile_semantics(
        validate({"shots": list(shots)}, [], shots[-1]["end_sec"]), regions
    )


def test_title_card_letterboxes_without_escalation():
    scenes = _scenes(_shot(0, 6, "title_card"))
    plan = reconcile(scenes, [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    assert plan[0]["inner_ar"] == (16, 9)
    assert plan[0]["trace"]["source"] == "semantic_graphic"
    assert not collect_escalation_points(plan)


def test_poster_with_detected_face_still_letterboxes():
    # The SonyLIV class: key-art "face" on a static poster must not force a
    # tight crop — content_kind overrides the detection.
    scenes = _scenes(_shot(0, 6, "poster_static"))
    tracked = [_frame(t, [_tr(1, 0.5, w=0.2, conf=0.55)]) for t in range(7)]
    plan = reconcile(scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    assert plan[0]["inner_ar"] == (16, 9)
    assert plan[0]["trace"]["source"] == "semantic_graphic"
    assert not collect_escalation_points(plan)


def test_broll_center_crops_confidently_without_escalation():
    scenes = _scenes(_shot(0, 6, "broll_scenery"))
    plan = reconcile(scenes, [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    assert plan[0]["inner_ar"] == RUNGS[0]  # tightest rung, centered
    assert not collect_escalation_points(plan)  # no no_subject question


def test_text_keep_raises_coverage_before_the_dp():
    # talking head + essential caption measured [0.1, 0.9]: the crop follows the
    # face but C is raised so the rung DP natively lands on 16:9 — no post-hoc
    # widening, and the trace carries the justifying band for the eval.
    shot = _shot(
        0,
        6,
        "talking_head",
        text_elements=[
            {"kind": "subtitle", "importance": "essential", "extent": "full_width"}
        ],
    )
    region = {
        "box": [0.1, 0.8, 0.9, 0.88],
        "times": [0.0, 2.0, 4.0, 6.0],
        "video_frac": 0.5,
        "kind": "candidate",
    }
    scenes = _scenes(shot, regions=[region])
    tracked = [_frame(t, [_tr(1, 0.5)]) for t in range(7)]
    plan = reconcile(scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    assert plan[0]["inner_ar"] == (16, 9)
    assert plan[0]["trace"]["text_keep"] == [0.1, 0.9]
    assert plan[0]["crops"][0]["track_id"] == 1  # still following the face
    assert not collect_escalation_points(plan)  # no text thumbnail question


def test_semantic_shot_without_text_keep_crops_measured_text():
    # Measured wide text that Gemini did NOT judge essential → crop, silently.
    # (Legacy behavior would have escalated a thumbnail question.)
    scenes = _scenes(_shot(0, 6, "talking_head"))
    tracked = [_frame(t, [_tr(1, 0.5)]) for t in range(7)]
    texts = [
        {
            "time_sec": float(t),
            "coverage": 0.8,
            "span": (0.1, 0.9),
            "lines": [[0.1, 0.8, 0.9, 0.88]],
        }
        for t in range(7)
    ]
    plan = reconcile(
        scenes,
        tracked,
        cuts=[],
        src_w=SRC_W,
        src_h=SRC_H,
        duration=6.0,
        text_frames=texts,
    )
    assert plan[0]["inner_ar"] == RUNGS[0]
    assert not collect_escalation_points(plan)


def test_no_scenes_keeps_full_legacy_behavior():
    # The fallback ladder's bottom rung: scenes=[] must produce the legacy
    # escalations (here: no_subject for an empty shot).
    plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    pts = collect_escalation_points(plan)
    assert any(p["kind"] == "no_subject" for p in pts)


def test_multi_person_dialogue_unlocks_keep_both():
    scenes = _scenes(_shot(0, 6, "multi_person_dialogue"))
    tracked = [_frame(t, [_tr(1, 0.3, w=0.12), _tr(2, 0.7, w=0.12)]) for t in range(7)]
    plan = reconcile(scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
    assert plan[0]["layout"] in ("keep_both", "split")


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------
def test_flag_defaults_off_and_record_overrides(monkeypatch):
    monkeypatch.delenv("REFRAME_SEMANTIC_PASS", raising=False)
    assert semantic_pass_enabled() is False

    class Rec:
        semantic_pass = True

    assert semantic_pass_enabled(Rec()) is True
    monkeypatch.setenv("REFRAME_SEMANTIC_PASS", "on")
    assert semantic_pass_enabled() is True

    class RecOff:
        semantic_pass = False

    assert semantic_pass_enabled(RecOff()) is False


def test_reconciled_scene_shape_matches_legacy_consumers():
    scenes = _scenes(
        _shot(0, 6, "talking_head", key_subject={"desc": "host", "position": "left"})
    )
    s = scenes[0]
    assert s["scene_type"] == "dialogue"
    assert s["active_subject"] == "left"
    assert "start_sec" in s and "end_sec" in s and "layout" in s
    assert json.dumps(s)  # Firestore/JSON-safe

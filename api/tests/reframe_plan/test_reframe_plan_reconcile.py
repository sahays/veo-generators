"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_plan import (
    FACE_CONF_MIN,
    MAX_SEG_LEN,
    _boundaries,
    _competitors,
    _merge_short,
    _stable_tracks,
    attach_keypoints,
    collect_escalation_points,
    reconcile,
)

SRC_W, SRC_H = 1920, 1080


def _pframe(t: float, persons: list[dict[str, Any]]) -> dict[str, Any]:
    return {"time_sec": t, "persons": persons}


def _person(x: float, w: float = 0.15) -> dict[str, Any]:
    return {"x": x, "y": 0.5, "w": w, "h": 0.6, "confidence": 0.8}


def _frame(t: float, tracks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"time_sec": t, "tracks": tracks}


def _tr(tid: int, x: float, w: float = 0.1) -> dict[str, Any]:
    return {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": 0.9}


def _trc(tid: int, x: float, conf: float, w: float = 0.3) -> dict[str, Any]:
    """A tracked face carrying an explicit confidence (vs `_tr`'s fixed 0.9)."""
    return {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": conf}


def _ftrm(t: float, specs: list[tuple[Any, ...]]) -> dict[str, Any]:
    return {
        "time_sec": float(t),
        "tracks": [
            {
                "track_id": s[0],
                "x": s[1],
                "y": 0.45,
                "w": s[3] if len(s) > 3 else 0.1,
                "h": 0.2,
                "confidence": 0.9,
                "mouth": s[2],
            }
            for s in specs
        ],
    }


def _txt(t: float, coverage: float) -> dict[str, Any]:
    return {"time_sec": t, "coverage": coverage, "span": (0.05, 0.05 + coverage)}


def _split_scene(
    scene_type: str = "dialogue", layout: str | None = None
) -> dict[str, Any]:
    s: dict[str, Any] = {
        "start_sec": 0,
        "end_sec": 5,
        "scene_type": scene_type,
        "active_subject": "both",
    }
    if layout:
        s["layout"] = layout
    return s


# ---------------------------------------------------------------------------
# End-to-end reconcile
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_single_then_side_by_side(self) -> None:
        tracked = [
            _frame(0, [_tr(1, 0.5)]),
            _frame(2, [_tr(1, 0.5)]),
            _frame(4, [_tr(1, 0.5)]),
            _frame(6, [_tr(1, 0.3), _tr(2, 0.7)]),
            _frame(8, [_tr(1, 0.3), _tr(2, 0.7)]),
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "general",
                "active_subject": "center",
            },
            {
                "start_sec": 5,
                "end_sec": 10,
                "scene_type": "dialogue",
                "active_subject": "both",
            },
        ]
        plan = reconcile(
            scenes, tracked, cuts=[5.0], src_w=SRC_W, src_h=SRC_H, duration=10.0
        )
        assert len(plan) == 2
        a, b = plan
        assert a["layout"] == "single" and a["inner_ar"] == (9, 16)
        assert b["layout"] == "keep_both" and b["inner_ar"] == (1, 1)
        # keypoints are attached for rendering
        assert a["crops"][0]["keypoints"]

    def test_requires_full_width_retired(self) -> None:
        # RETIRED: Gemini requires_full_width no longer forces a rung. With no
        # detections and no measured text band, the plan defaults to a tight crop.
        tracked = [_frame(0, []), _frame(2, [])]
        scenes = [{"start_sec": 0, "end_sec": 4, "requires_full_width": True}]
        plan = reconcile(
            scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0
        )
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (9, 16)

    def test_no_detections_defaults_tight(self) -> None:
        plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (9, 16)
        assert plan[0]["layout"] == "single"

    def test_two_comparable_faces_escalate_subject(self) -> None:
        # Comparably PROMINENT faces (fused size × presence × confidence score),
        # neither clearly speaking → the single-subject pick is ambiguous →
        # escalate which-subject (#3/#4) to gemini-3.5.
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.08)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert any(p["kind"] == "subject_choice" for p in pts)

    def test_clearly_larger_face_dominates_without_escalation(self) -> None:
        # Equal presence but a 2.4× size gap is NOT ambiguity: the large face is
        # the subject, no Gemini call. (Under the retired frac-only ranking this
        # escalated — presence alone said "comparable".)
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.05)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert not any(p["kind"] == "subject_choice" for p in pts)
        assert plan[0]["crops"][0]["track_id"] == 1

    def test_large_intermittent_face_beats_small_persistent_face(self) -> None:
        # THE production wrong-subject case (rf-piemrxjm t=39-40s): a small face
        # present in every sample (w=0.16, frac=1.0) was framed while a face 3×
        # larger but intermittently tracked (w=0.51, frac=0.5) was clipped 35%.
        # Fused prominence must not lose the large face; frac-only framed the
        # small one and cropped the big one away.
        big_times = (0, 2, 4)  # frac 0.5 of the 6 samples — above STABLE_FRAC
        tracked = [
            _frame(
                t,
                [_tr(1, 0.3, w=0.16)]
                + ([_tr(2, 0.65, w=0.51)] if t in big_times else []),
            )
            for t in (0, 1, 2, 3, 4, 5)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        crop = plan[0]["crops"][0]
        kept = [crop.get("track_id")] + list(crop.get("track_ids") or [])
        assert 2 in kept, f"large face lost again: {plan[0]}"

    def test_two_equal_faces_keep_both(self) -> None:
        # PRODUCT RULE: equally present AND equally sized people are framed
        # together — no single-subject pick, no escalation needed.
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.12)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert plan[0]["layout"] == "keep_both"
        assert plan[0]["crops"][0]["track_ids"] == [1, 2]
        assert not collect_escalation_points(plan)

    def test_merge_keeps_content_changes_separate(self) -> None:
        # A speaker shot and a full-screen graphic both plan to 9:16, but must NOT
        # merge into one segment — else one Gemini verdict governs both and the
        # graphic gets cropped. Distinguished by face-presence and escalation key.
        def seg(s: Any, e: Any, nf: Any, ek: Any = None) -> Any:
            d = {
                "start": s,
                "end": e,
                "inner_ar": (9, 16),
                "layout": "single",
                "crops": [{"x_target": 0.5}],
                "trace": {"n_faces": nf},
                "reason": "",
                "escalate": None,
            }
            if ek:
                d["escalate"] = {"key": ek, "kind": "text_presence"}
            return d

        # speaker (face) → graphic (no face): kept separate
        assert len(_merge_short([seg(0, 5, 1), seg(5, 10, 0)], 2.0)) == 2
        # two identical speaker cells: merged (stability)
        assert len(_merge_short([seg(0, 5, 1), seg(5, 10, 1)], 2.0)) == 1
        # a caption appears mid-shot (different escalation key): kept separate
        assert (
            len(
                _merge_short(
                    [seg(0, 5, 1), seg(5, 10, 1, "text:left:0.0-0.6@0.5")], 2.0
                )
            )
            == 2
        )

    def test_single_face_no_subject_escalation(self) -> None:
        tracked = [_frame(t, [_tr(1, 0.5, w=0.15)]) for t in (0, 2, 4)]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert not any(
            p["kind"] == "subject_choice" for p in collect_escalation_points(plan)
        )

    def test_no_detection_escalates_no_subject(self) -> None:
        # No face, no person, no text band → escalate "is this a full-frame graphic?"
        plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert len(pts) == 1 and pts[0]["kind"] == "no_subject"
        assert plan[0]["inner_ar"] == (9, 16)  # fallback: center crop

    def test_no_subject_yields_to_text_band(self) -> None:
        # If a wide text band is present, the text escalation wins (not no_subject).
        text_frames = [_txt(t, 0.9) for t in range(6)]
        plan = reconcile(
            [],
            [],
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=6.0,
            text_frames=text_frames,
        )
        kinds = {p["kind"] for p in collect_escalation_points(plan)}
        assert kinds == {"text_presence"}

    def test_gemini_overcoverage_retired_crops_tight(self) -> None:
        # The rf-0ma5249p defect, now fixed by retiring the floor: a single narrow
        # face that Gemini reports as near-full-width coverage. The coverage floor is
        # gone, so WITH or WITHOUT Gemini scenes the plan crops tight to the detected
        # face — Gemini's coverage number no longer letterboxes.
        tracked = [_frame(t, [_tr(1, 0.5, w=0.2)]) for t in (0, 2, 4)]
        over = [
            {
                "start_sec": 0,
                "end_sec": 6,
                "scene_type": "general",
                "active_subject": "center",
                "min_horizontal_coverage": 0.99,
            }
        ]
        gemini = reconcile(
            over, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0
        )
        deterministic = reconcile(
            [], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0
        )
        assert gemini[0]["inner_ar"] == (9, 16)  # coverage floor retired → tight
        assert deterministic[0]["inner_ar"] == (9, 16)  # same: CPU face width only

    def test_person_fallback_when_no_face(self) -> None:
        # No faces, but a person walking away (e.g. trolley-at-night shot).
        persons = [_pframe(0, [_person(0.6)]), _pframe(2, [_person(0.62)])]
        scenes = [{"start_sec": 0, "end_sec": 4, "scene_type": "wide"}]
        plan = reconcile(
            scenes,
            [],
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            person_frames=persons,
        )
        assert len(plan) == 1
        assert plan[0]["crops"][0]["source"] == "person"
        # focal target follows the person, not default-center
        assert plan[0]["crops"][0]["x_target"] > 0.55


class TestStableTracksConfidence:
    def test_stable_tracks_aggregates_mean_confidence(self) -> None:
        win = [
            _frame(0, [_trc(1, 0.5, 0.4)]),
            _frame(1, [_trc(1, 0.5, 0.6)]),
            _frame(2, [_trc(1, 0.5, 0.8)]),
        ]
        stable = _stable_tracks(win)
        assert len(stable) == 1
        assert abs(stable[0]["conf"] - 0.6) < 1e-6  # (0.4+0.6+0.8)/3

    def test_competitors_surface_confidence(self) -> None:
        win = [_frame(t, [_trc(1, 0.5, 0.42)]) for t in (0, 1, 2)]
        comp = _competitors(_stable_tracks(win), {})
        assert comp and comp[0]["conf"] == 0.42


class TestWeakSubjectEscalation:
    """#7b: a sole LOW-confidence face may be a logo/title card (rf-udcpl2hd)."""

    def test_low_conf_sole_face_escalates_graphic(self) -> None:
        # A single face below FACE_CONF_MIN, no Gemini hint → escalate weak_subject.
        tracked = [_frame(t, [_trc(1, 0.48, 0.35, w=0.31)]) for t in (0, 1, 2, 3)]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0)
        pts = collect_escalation_points(plan)
        assert [p["kind"] for p in pts] == ["weak_subject"]
        p = pts[0]
        assert p["fallback"]["action"] == "crop"  # follow face pending verdict
        assert "crop_keeps" in p["facts"]
        assert p["key"].startswith("graphic:")
        # fallback render still crops tight to the (possibly false) face
        assert plan[0]["inner_ar"] == (9, 16)

    def test_high_conf_sole_face_does_not_escalate(self) -> None:
        tracked = [_frame(t, [_trc(1, 0.48, 0.95, w=0.31)]) for t in (0, 1, 2, 3)]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0)
        assert collect_escalation_points(plan) == []

    def test_low_conf_face_with_side_text_routes_to_text_not_graphic(self) -> None:
        # rf-r5eik9j2 seg2/seg3: a sole low-conf face (a running person) with
        # product callouts reaching both edges. The text-band conflict must PRE-EMPT
        # the person-vs-graphic question — otherwise Gemini is asked "person or
        # graphic?", sees the person, and crops the callouts off. A both-sides band
        # sets `escalate` before the graphic branch, so the shot escalates
        # `text_presence` (which carries the band for the letterbox widen).
        tracked = [_frame(t, [_trc(1, 0.5, 0.35, w=0.2)]) for t in (0, 1, 2, 3)]
        text_frames = [_txt(t, 0.9) for t in range(5)]  # span (0.05, 0.95): both sides
        plan = reconcile(
            [],
            tracked,
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            text_frames=text_frames,
        )
        pts = collect_escalation_points(plan)
        assert [p["kind"] for p in pts] == ["text_presence"]  # not weak_subject
        assert pts[0]["facts"]["check_side"] == "both"
        assert pts[0]["facts"]["band"]  # carried for the containment-aware widen

    def test_gemini_subject_hint_suppresses_graphic_escalation(self) -> None:
        # If a Gemini scene already named the subject, trust it — no graphic check.
        tracked = [_frame(t, [_trc(1, 0.48, 0.35, w=0.31)]) for t in (0, 1, 2, 3)]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 4,
                "scene_type": "general",
                "active_subject": "center",
            }
        ]
        plan = reconcile(
            scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0
        )
        assert not any(
            p["kind"] == "weak_subject" for p in collect_escalation_points(plan)
        )

    def test_two_faces_one_weak_uses_subject_path_not_graphic(self) -> None:
        # The graphic check is for a SOLE face; ≥2 faces stay on the subject path.
        tracked = [
            _frame(t, [_trc(1, 0.3, 0.35, w=0.2), _trc(2, 0.7, 0.4, w=0.2)])
            for t in (0, 1, 2, 3)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0)
        kinds = {p["kind"] for p in collect_escalation_points(plan)}
        assert "weak_subject" not in kinds

    def test_threshold_constant_is_sane(self) -> None:
        assert 0.3 < FACE_CONF_MIN < 0.9


class TestAttachKeypoints:
    def test_smooths_focal_points_into_keypoints(self) -> None:
        tracked = [
            _frame(0, [_tr(1, 0.3)]),
            _frame(1, [_tr(1, 0.4)]),
            _frame(2, [_tr(1, 0.5)]),
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 3,
                "active_subject": "center",
                "scene_type": "action",
            }
        ]
        plan = reconcile(
            scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=3.0
        )
        assert plan[0]["scene_type"] == "action"  # velocity derived from this
        attach_keypoints(plan, fps=30)
        kps = plan[0]["crops"][0]["keypoints"]
        assert len(kps) >= 2
        # keypoints are absolute-time tuples within the segment
        assert all(0.0 <= t <= 3.0 for (t, _x, _y) in kps)
        assert all(0.0 <= x <= 1.0 for (_t, x, _y) in kps)


# ---------------------------------------------------------------------------
# Robustness fixes (rf-dx59lar6 regressions)
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_long_span_is_subdivided(self) -> None:
        # A 5-minute stretch with no detected cuts must not be one segment.
        bounds = _boundaries([], 300.0)
        assert len(bounds) > 1
        assert all((e - s) <= MAX_SEG_LEN + 1e-6 for s, e in bounds)
        assert bounds[0][0] == 0.0 and bounds[-1][1] == 300.0

    def test_huge_single_face_not_letterboxed(self) -> None:
        # A foreground / mis-measured face (w≈0.96) must not force 16:9.
        tracked = [_frame(t, [_tr(1, 0.3, w=0.96)]) for t in range(0, 6)]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 6,
                "scene_type": "general",
                "active_subject": "center",
                "min_horizontal_coverage": 0.3,
            }
        ]
        plan = reconcile(scenes, tracked, cuts=[], src_w=3840, src_h=2160, duration=6.0)
        assert all(s["inner_ar"] != (16, 9) for s in plan)

    def test_distinct_subjects_not_merged(self) -> None:
        # Adjacent cells following different subjects stay separate (re-frame each).
        tr = [_frame(t, [_tr(1, 0.2)]) for t in range(0, 5)]
        tr += [_frame(t, [_tr(2, 0.8)]) for t in range(5, 10)]
        sc = [
            {
                "start_sec": 0,
                "end_sec": 10,
                "scene_type": "general",
                "active_subject": "largest",
                "min_horizontal_coverage": 0.3,
            }
        ]
        plan = reconcile(sc, tr, cuts=[], src_w=3840, src_h=2160, duration=10.0)
        xs = [round(s["crops"][0]["x_target"], 1) for s in plan]
        assert 0.2 in xs and 0.8 in xs  # both subjects framed, not smeared

    def test_static_subject_centered_despite_boundary_jitter(self) -> None:
        # Face stable at 0.50 with one undershoot sample (0.44) at the start.
        # Must center on the median, not freeze off-center (the Pichai bug).
        tracked = [
            _frame(float(t), [_tr(1, 0.44 if t == 0 else 0.50)]) for t in range(5)
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "dialogue",
                "active_subject": "center",
            }
        ]
        plan = reconcile(scenes, tracked, cuts=[], src_w=854, src_h=480, duration=5.0)
        attach_keypoints(plan, fps=25)
        xs = [x for _t, x, _y in plan[0]["crops"][0]["keypoints"]]
        assert all(abs(x - 0.5) < 0.02 for x in xs), xs

"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_plan import (
    RUNGS,
    MAX_SEG_LEN,
    rung_coverage,
    pick_rung,
    reconcile,
    attach_keypoints,
    _boundaries,
    _global_label_map,
    _match_track,
    _keep_both_pair,
    _merge_short,
)


def _pframe(t, persons):
    return {"time_sec": t, "persons": persons}


def _person(x, w=0.15):
    return {"x": x, "y": 0.5, "w": w, "h": 0.6, "confidence": 0.8}


SRC_W, SRC_H = 1920, 1080


def _frame(t, tracks):
    return {"time_sec": t, "tracks": tracks}


def _tr(tid, x, w=0.1):
    return {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": 0.9}


# ---------------------------------------------------------------------------
# Rung math
# ---------------------------------------------------------------------------


class TestRungCoverage:
    def test_ladder_is_monotonic(self):
        covs = [rung_coverage(r, SRC_W, SRC_H) for r in RUNGS]
        assert covs == sorted(covs)  # tightest → loosest

    def test_known_values(self):
        assert abs(rung_coverage((9, 16), SRC_W, SRC_H) - 0.316) < 0.01
        assert abs(rung_coverage((1, 1), SRC_W, SRC_H) - 0.5625) < 0.01
        assert rung_coverage((16, 9), SRC_W, SRC_H) == 1.0  # clamped


class TestPickRung:
    def test_narrow_subject_picks_tightest(self):
        assert pick_rung(0.15, SRC_W, SRC_H) == (9, 16)

    def test_wide_subject_picks_looser(self):
        assert pick_rung(0.54, SRC_W, SRC_H) == (1, 1)

    def test_full_width_picks_letterbox(self):
        assert pick_rung(0.99, SRC_W, SRC_H) == (16, 9)

    def test_tolerance_prefers_tighter_near_boundary(self):
        # 0.60 is just above 1:1's 0.5625 — tolerance keeps it at 1:1, not 16:9.
        assert pick_rung(0.60, SRC_W, SRC_H) == (1, 1)
        # but a genuinely wide requirement still letterboxes
        assert pick_rung(0.75, SRC_W, SRC_H) == (16, 9)

    def test_hysteresis_keeps_prev_when_it_still_fits(self):
        # required fits in 4:5; prev is the looser 1:1 → stay to avoid flip-flop.
        assert pick_rung(0.40, SRC_W, SRC_H, prev=(1, 1)) == (1, 1)

    def test_hysteresis_still_tightens_when_needed(self):
        # prev was loose but a much tighter rung now suffices → tighten.
        assert pick_rung(0.10, SRC_W, SRC_H, prev=(1, 1)) == (9, 16)


# ---------------------------------------------------------------------------
# Entity matching
# ---------------------------------------------------------------------------


class TestEntityMatch:
    def test_global_label_map_by_frequency(self):
        frames = [_frame(0, [_tr(7, 0.3), _tr(2, 0.7)]), _frame(2, [_tr(7, 0.3)])]
        lm = _global_label_map(frames)
        assert lm["A"] == 7  # most visible
        assert lm["B"] == 2

    def test_match_track_a_resolves_to_most_visible(self):
        stable = [
            {"track_id": 7, "x": 0.3, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.7, "w": 0.1, "frac": 0.5},
        ]
        lm = {"A": 7, "B": 2}
        got = _match_track(stable, {"active_subject": "Track A"}, lm)
        assert got["track_id"] == 7  # not the lowest track_id (the v1 bug)

    def test_match_left_right(self):
        stable = [
            {"track_id": 1, "x": 0.2, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.8, "w": 0.1, "frac": 1.0},
        ]
        assert _match_track(stable, {"active_subject": "right"}, {})["track_id"] == 2
        assert _match_track(stable, {"active_subject": "left"}, {})["track_id"] == 1


class TestKeepBothPair:
    def test_two_far_apart_dialogue(self):
        stable = [
            {"track_id": 1, "x": 0.3, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.7, "w": 0.1, "frac": 1.0},
        ]
        assert _keep_both_pair(stable, {"scene_type": "dialogue"}) is not None

    def test_close_together_is_single(self):
        stable = [
            {"track_id": 1, "x": 0.48, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.52, "w": 0.1, "frac": 1.0},
        ]
        assert _keep_both_pair(stable, {"scene_type": "dialogue"}) is None

    def test_single_track_is_none(self):
        assert (
            _keep_both_pair([{"track_id": 1, "x": 0.5, "w": 0.1, "frac": 1.0}], {})
            is None
        )


# ---------------------------------------------------------------------------
# Merge / dwell
# ---------------------------------------------------------------------------


class TestMergeShort:
    def _seg(self, start, end, ar, layout="single"):
        return {
            "start": start,
            "end": end,
            "inner_ar": ar,
            "layout": layout,
            "crops": [{"track_id": 1, "x_target": 0.5}],
            "reason": "",
        }

    def test_collapses_identical_neighbors(self):
        segs = [self._seg(0, 5, (9, 16)), self._seg(5, 10, (9, 16))]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1 and out[0]["end"] == 10

    def test_folds_short_segment_into_prev_keeping_looser(self):
        segs = [self._seg(0, 5, (9, 16)), self._seg(5, 5.5, (1, 1))]  # 0.5s blip
        out = _merge_short(segs, 2.0)
        assert len(out) == 1
        assert out[0]["inner_ar"] == (1, 1)  # looser rung wins (never crop content)
        assert out[0]["end"] == 5.5


# ---------------------------------------------------------------------------
# End-to-end reconcile
# ---------------------------------------------------------------------------


class TestReconcile:
    def test_single_then_side_by_side(self):
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

    def test_requires_full_width_forces_letterbox(self):
        tracked = [_frame(0, []), _frame(2, [])]
        scenes = [{"start_sec": 0, "end_sec": 4, "requires_full_width": True}]
        plan = reconcile(
            scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0
        )
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (16, 9)

    def test_no_detections_defaults_tight(self):
        plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (9, 16)
        assert plan[0]["layout"] == "single"

    def test_person_fallback_when_no_face(self):
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


class TestAttachKeypoints:
    def test_smooths_focal_points_into_keypoints(self):
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
    def test_long_span_is_subdivided(self):
        # A 5-minute stretch with no detected cuts must not be one segment.
        bounds = _boundaries([], 300.0)
        assert len(bounds) > 1
        assert all((e - s) <= MAX_SEG_LEN + 1e-6 for s, e in bounds)
        assert bounds[0][0] == 0.0 and bounds[-1][1] == 300.0

    def test_huge_single_face_not_letterboxed(self):
        # A foreground / mis-measured face (w≈0.96) must not force 16:9.
        tracked = [_frame(t, [_tr(1, 0.3, w=0.96)]) for t in range(0, 6)]
        scenes = [
            {"start_sec": 0, "end_sec": 6, "scene_type": "general",
             "active_subject": "center", "min_horizontal_coverage": 0.3}
        ]
        plan = reconcile(scenes, tracked, cuts=[], src_w=3840, src_h=2160, duration=6.0)
        assert all(s["inner_ar"] != (16, 9) for s in plan)

    def test_distinct_subjects_not_merged(self):
        # Adjacent cells following different subjects stay separate (re-frame each).
        tr = [_frame(t, [_tr(1, 0.2)]) for t in range(0, 5)]
        tr += [_frame(t, [_tr(2, 0.8)]) for t in range(5, 10)]
        sc = [{"start_sec": 0, "end_sec": 10, "scene_type": "general",
               "active_subject": "largest", "min_horizontal_coverage": 0.3}]
        plan = reconcile(sc, tr, cuts=[], src_w=3840, src_h=2160, duration=10.0)
        xs = [round(s["crops"][0]["x_target"], 1) for s in plan]
        assert 0.2 in xs and 0.8 in xs  # both subjects framed, not smeared

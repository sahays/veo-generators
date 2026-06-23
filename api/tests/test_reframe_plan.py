"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_plan import (
    RUNGS,
    RUNGS_BY_CANVAS,
    MAX_SEG_LEN,
    rung_coverage,
    pick_rung,
    reconcile,
    attach_keypoints,
    pick_active_speaker,
    reconcile_text_coverage,
    TEXT_SELF_TRIGGER,
    _boundaries,
    _global_label_map,
    _match_track,
    _keep_both_pair,
    _merge_short,
    _segment_text_coverage,
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


class TestPickRung34:
    """3:4 is a fixed full-bleed crop: a single-rung ladder, always (3,4)."""

    R34 = RUNGS_BY_CANVAS["3:4"]

    def test_ladder_is_just_full_bleed(self):
        assert self.R34 == [(3, 4)]

    def test_always_picks_3x4_regardless_of_coverage(self):
        # No looser rungs → never letterboxes, even for very wide content.
        for req in (0.0, 0.2, 0.42, 0.55, 0.9, 1.0):
            assert pick_rung(req, SRC_W, SRC_H, rungs=self.R34) == (3, 4)

    def test_hysteresis_is_noop_with_one_rung(self):
        assert pick_rung(0.9, SRC_W, SRC_H, prev=(3, 4), rungs=self.R34) == (3, 4)


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

    def test_distinct_subjects_not_merged(self):
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

    def test_static_subject_centered_despite_boundary_jitter(self):
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


# ---------------------------------------------------------------------------
# Active-speaker detection (Phase 2)
# ---------------------------------------------------------------------------


def _ftrm(t, specs):
    # specs: list of (track_id, x, mouth)
    return {
        "time_sec": float(t),
        "tracks": [
            {
                "track_id": tid,
                "x": x,
                "y": 0.45,
                "w": 0.1,
                "h": 0.2,
                "confidence": 0.9,
                "mouth": m,
            }
            for tid, x, m in specs
        ],
    }


class TestActiveSpeaker:
    TALK = [0.10, 0.45, 0.10, 0.50, 0.12]  # mouth oscillates → speaking
    STILL = [0.20, 0.21, 0.20, 0.19, 0.20]  # ~steady → listening

    def test_picks_clear_talker(self):
        assert pick_active_speaker({1: self.TALK, 2: self.STILL}) == 1

    def test_both_moving_is_ambiguous(self):
        assert pick_active_speaker({1: self.TALK, 2: self.TALK}) is None

    def test_silence_returns_none(self):
        assert pick_active_speaker({1: self.STILL, 2: self.STILL}) is None

    def test_too_few_samples_returns_none(self):
        assert pick_active_speaker({1: [0.1, 0.5]}) is None

    def test_reconcile_frames_speaker_not_keepboth(self):
        frames = [
            _ftrm(t, [(1, 0.30, self.TALK[t]), (2, 0.70, self.STILL[t])])
            for t in range(5)
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "dialogue",
                "active_subject": "both",
            }
        ]
        plan = reconcile(scenes, frames, cuts=[], src_w=1920, src_h=1080, duration=5.0)
        assert plan[0]["layout"] == "single"
        assert plan[0]["crops"][0]["source"] == "speaker"
        assert abs(plan[0]["crops"][0]["x_target"] - 0.30) < 0.05  # on the talker

    def test_reconcile_both_talking_keeps_both(self):
        frames = [
            _ftrm(t, [(1, 0.30, self.TALK[t]), (2, 0.70, self.TALK[t])])
            for t in range(5)
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "dialogue",
                "active_subject": "both",
            }
        ]
        plan = reconcile(scenes, frames, cuts=[], src_w=1920, src_h=1080, duration=5.0)
        assert plan[0]["layout"] == "keep_both"


# ---------------------------------------------------------------------------
# Wide-text coverage (Phase 2): Gemini flags, CPU measures the extent
# ---------------------------------------------------------------------------


def _txt(t, coverage):
    return {"time_sec": t, "coverage": coverage, "span": (0.05, 0.05 + coverage)}


class TestReconcileTextCoverage:
    def test_gemini_text_refined_down_by_measurement(self):
        # Gemini says full-width (1.0) but the title is only 0.7 wide → use 0.7,
        # so we take 1:1 instead of a needless full 16:9 letterbox.
        assert reconcile_text_coverage(1.0, 0.7, gemini_text_intent=True) == 0.7

    def test_gemini_text_kept_when_detector_blind(self):
        # Gemini flags text but the detector found none → never chop; keep Gemini.
        assert reconcile_text_coverage(1.0, 0.0, gemini_text_intent=True) == 1.0

    def test_measurement_self_triggers_when_gemini_silent(self):
        # Gemini didn't flag text, but a confidently wide band is present → trust it.
        assert (
            reconcile_text_coverage(0.3, TEXT_SELF_TRIGGER, gemini_text_intent=False)
            == TEXT_SELF_TRIGGER
        )

    def test_weak_measurement_ignored_when_gemini_silent(self):
        # A weak band with no Gemini flag is treated as a false positive.
        assert reconcile_text_coverage(0.3, 0.4, gemini_text_intent=False) == 0.3


class TestSegmentTextCoverage:
    def test_persistent_text_returns_median(self):
        frames = [_txt(t, 0.8) for t in range(5)]
        assert abs(_segment_text_coverage(frames, 0, 4) - 0.8) < 1e-9

    def test_transient_flash_rejected(self):
        # One wide frame out of five → below the persistence floor → 0.
        frames = [_txt(0, 0.9)] + [_txt(t, 0.0) for t in range(1, 5)]
        assert _segment_text_coverage(frames, 0, 4) == 0.0

    def test_empty_or_none_is_zero(self):
        assert _segment_text_coverage(None, 0, 5) == 0.0
        assert _segment_text_coverage([], 0, 5) == 0.0


class TestReconcileWithText:
    def test_measured_wide_text_forces_letterbox(self):
        # No faces, Gemini gave no coverage, but the detector sees full-width text
        # across the whole clip → plan must letterbox (16:9), source "center".
        scenes = [{"start_sec": 0, "end_sec": 5, "scene_type": "general"}]
        text_frames = [_txt(t, 0.95) for t in range(6)]
        plan = reconcile(
            scenes,
            [],
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=5.0,
            text_frames=text_frames,
        )
        assert tuple(plan[0]["inner_ar"]) == (16, 9)
        assert plan[0]["trace"]["text_measured"] >= 0.9

    def test_full_width_flag_refined_down(self):
        # Gemini flags full-width but the measured title is ~0.6 wide → a tighter
        # rung than 16:9 (no needless full letterbox).
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "general",
                "requires_full_width": True,
            }
        ]
        text_frames = [_txt(t, 0.6) for t in range(6)]
        plan = reconcile(
            scenes,
            [],
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=5.0,
            text_frames=text_frames,
        )
        assert tuple(plan[0]["inner_ar"]) != (16, 9)


# ---------------------------------------------------------------------------
# Vertical-split layout (Phase 3): static, far-apart two-person dialogue
# ---------------------------------------------------------------------------


def _split_scene(scene_type="dialogue", layout=None):
    s = {"start_sec": 0, "end_sec": 5, "scene_type": scene_type, "active_subject": "both"}
    if layout:
        s["layout"] = layout
    return s


class TestSplitLayout:
    # Two far-apart, static, persistent faces; neither mouth clearly dominates.
    def _frames(self, x1=0.25, x2=0.75, n=5):
        return [_ftrm(t, [(1, x1, 0.2), (2, x2, 0.2)]) for t in range(n)]

    def _plan(self, frames, scene, duration=4.0):
        return reconcile(
            [scene], frames, cuts=[], src_w=1920, src_h=1080, duration=duration
        )

    def test_static_far_apart_dialogue_splits(self):
        plan = self._plan(self._frames(), _split_scene())
        assert len(plan) == 1
        seg = plan[0]
        assert seg["layout"] == "split"
        assert seg["inner_ar"] is None
        assert len(seg["crops"]) == 2
        # left subject → top panel, right → bottom (geometric, stable).
        top, bot = seg["crops"]
        assert top["track_id"] == 1 and top["source"] == "split_top"
        assert bot["track_id"] == 2 and bot["source"] == "split_bottom"
        assert seg["trace"]["source"] == "split"
        # both panels are renderable (keypoints attached).
        assert top["keypoints"] and bot["keypoints"]

    def test_side_by_side_layout_also_splits(self):
        plan = self._plan(self._frames(), _split_scene("general", "side_by_side"))
        assert plan[0]["layout"] == "split"

    def test_close_together_is_single_not_split(self):
        plan = self._plan(self._frames(x1=0.45, x2=0.55), _split_scene())
        assert plan[0]["layout"] == "single"

    def test_moving_two_shot_keeps_both_not_split(self):
        # One subject drifts > SPLIT_MAX_MOTION → too busy to stack → keep_both.
        frames = [
            _ftrm(t, [(1, 0.25 + 0.04 * t, 0.2), (2, 0.75, 0.2)]) for t in range(5)
        ]
        seg = self._plan(frames, _split_scene())[0]
        assert seg["layout"] == "keep_both"

    def test_short_shot_does_not_split(self):
        # Below SPLIT_MIN_DWELL (3s) → stacking would read as a glitch → keep_both.
        plan = self._plan(self._frames(n=3), _split_scene(), duration=2.0)
        assert plan[0]["layout"] == "keep_both"

    def test_non_dialogue_does_not_split(self):
        # Wide separation but Gemini didn't call it dialogue/side_by_side.
        seg = self._plan(self._frames(), _split_scene("general"))[0]
        assert seg["layout"] == "keep_both"

    def test_dominant_speaker_follows_single_not_split(self):
        # If one mouth clearly dominates, follow that speaker instead of stacking.
        talk = [0.10, 0.45, 0.10, 0.50, 0.12]
        frames = [_ftrm(t, [(1, 0.25, talk[t]), (2, 0.75, 0.2)]) for t in range(5)]
        seg = self._plan(frames, _split_scene())[0]
        assert seg["layout"] == "single"
        assert seg["crops"][0]["source"] == "speaker"

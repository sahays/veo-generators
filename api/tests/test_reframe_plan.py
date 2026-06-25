"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_plan import (
    RUNGS,
    RUNGS_BY_CANVAS,
    MAX_SEG_LEN,
    FACE_CONF_MIN,
    rung_coverage,
    pick_rung,
    reconcile,
    collect_escalation_points,
    attach_keypoints,
    pick_active_speaker,
    _boundaries,
    _global_label_map,
    _match_track,
    _keep_both_pair,
    _merge_short,
    _segment_text_band,
    _maybe_text_escalation,
    _maybe_subject_escalation,
    _motion_scene_type,
    _side_of,
    _stable_tracks,
    _competitors,
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


class TestTextEscalationPredicate:
    # subject at x=0.5 → tight 9:16 crop keeps ~[0.342, 0.658]; SIDE_TEXT_MARGIN=0.06.
    def _esc(self, x0, x1, cov=0.85, subj=0.5):
        return _maybe_text_escalation(
            (cov, (x0, x1)), subj, 1, SRC_W, SRC_H, RUNGS, 0.0, 4.0
        )

    def test_band_inside_crop_window_no_escalation(self):
        # A band fully behind the subject (within the kept region) → nothing cut.
        assert self._esc(0.40, 0.62) is None

    def test_band_below_wide_threshold_no_escalation(self):
        # cov < TEXT_WIDE_MIN (0.50): not a persistent wide band.
        assert self._esc(0.05, 0.95, cov=0.3) is None

    def test_band_left_only(self):
        e = self._esc(0.05, 0.55)  # pokes past the left edge, not the right
        assert e is not None and e["facts"]["check_side"] == "left"

    def test_band_right_only(self):
        e = self._esc(0.45, 0.97)
        assert e is not None and e["facts"]["check_side"] == "right"

    def test_band_both_sides(self):
        e = self._esc(0.05, 0.97)
        assert e is not None and e["facts"]["check_side"] == "both"

    def test_margin_boundary_not_escalated(self):
        # Just within margin on each side (0.342-0.06=0.282 .. 0.658+0.06=0.718).
        assert self._esc(0.29, 0.71) is None

    def test_offcenter_subject_shifts_window(self):
        # Subject far left → a right-side band is now "cut", a left one isn't.
        e = self._esc(0.30, 0.95, subj=0.25)
        assert e is not None and e["facts"]["check_side"] == "right"


class TestSubjectEscalationPredicate:
    def _stable(self, *xf):
        return [
            {"track_id": i + 1, "x": x, "w": 0.12, "frac": f}
            for i, (x, f) in enumerate(xf)
        ]

    def test_single_face_no_escalation(self):
        st = self._stable((0.5, 1.0))
        assert _maybe_subject_escalation(st, st[0], 0.0, 4.0) is None

    def test_one_clearly_dominant_no_escalation(self):
        # 2nd face only 0.3 as present as the 1st (< SUBJECT_AMBIG_RATIO 0.6).
        st = self._stable((0.3, 1.0), (0.7, 0.3))
        assert _maybe_subject_escalation(st, st[0], 0.0, 4.0) is None

    def test_two_comparable_faces_escalate(self):
        st = self._stable((0.3, 1.0), (0.7, 0.9))
        e = _maybe_subject_escalation(st, st[0], 0.0, 4.0)
        assert e is not None and len(e["facts"]["candidates"]) == 2

    def test_side_of_buckets(self):
        assert (_side_of(0.2), _side_of(0.5), _side_of(0.8)) == (
            "left",
            "center",
            "right",
        )


class TestMotionSceneType:
    def _d(self, tid):
        return {"crops": [{"track_id": tid}]}

    def test_static_subject_is_general(self):
        win = [_frame(t, [_tr(1, 0.5)]) for t in range(4)]
        assert _motion_scene_type(self._d(1), win, []) == "general"

    def test_fast_moving_subject_is_action(self):
        win = [_frame(0, [_tr(1, 0.15)]), _frame(1, [_tr(1, 0.85)])]  # spread 0.7
        assert _motion_scene_type(self._d(1), win, []) == "action"

    def test_no_face_uses_person_spread(self):
        pf = [_pframe(0, [_person(0.1)]), _pframe(1, [_person(0.9)])]
        assert _motion_scene_type({"crops": [{"track_id": None}]}, [], pf) == "action"


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

    def test_requires_full_width_retired(self):
        # RETIRED: Gemini requires_full_width no longer forces a rung. With no
        # detections and no measured text band, the plan defaults to a tight crop.
        tracked = [_frame(0, []), _frame(2, [])]
        scenes = [{"start_sec": 0, "end_sec": 4, "requires_full_width": True}]
        plan = reconcile(
            scenes, tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0
        )
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (9, 16)

    def test_no_detections_defaults_tight(self):
        plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert len(plan) == 1
        assert plan[0]["inner_ar"] == (9, 16)
        assert plan[0]["layout"] == "single"

    def test_two_comparable_faces_escalate_subject(self):
        # Two close, comparably-present faces, neither clearly speaking → the single-
        # subject pick is ambiguous → escalate which-subject (#3/#4) to gemini-3.5.
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.12)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert any(p["kind"] == "subject_choice" for p in pts)

    def test_merge_keeps_content_changes_separate(self):
        # A speaker shot and a full-screen graphic both plan to 9:16, but must NOT
        # merge into one segment — else one Gemini verdict governs both and the
        # graphic gets cropped. Distinguished by face-presence and escalation key.
        def seg(s, e, nf, ek=None):
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

    def test_single_face_no_subject_escalation(self):
        tracked = [_frame(t, [_tr(1, 0.5, w=0.15)]) for t in (0, 2, 4)]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert not any(
            p["kind"] == "subject_choice" for p in collect_escalation_points(plan)
        )

    def test_no_detection_escalates_no_subject(self):
        # No face, no person, no text band → escalate "is this a full-frame graphic?"
        plan = reconcile([], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert len(pts) == 1 and pts[0]["kind"] == "no_subject"
        assert plan[0]["inner_ar"] == (9, 16)  # fallback: center crop

    def test_no_subject_yields_to_text_band(self):
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

    def test_gemini_overcoverage_retired_crops_tight(self):
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


def _trc(tid, x, conf, w=0.3):
    """A tracked face carrying an explicit confidence (vs `_tr`'s fixed 0.9)."""
    return {"track_id": tid, "x": x, "y": 0.45, "w": w, "h": 0.2, "confidence": conf}


class TestStableTracksConfidence:
    def test_stable_tracks_aggregates_mean_confidence(self):
        win = [
            _frame(0, [_trc(1, 0.5, 0.4)]),
            _frame(1, [_trc(1, 0.5, 0.6)]),
            _frame(2, [_trc(1, 0.5, 0.8)]),
        ]
        stable = _stable_tracks(win)
        assert len(stable) == 1
        assert abs(stable[0]["conf"] - 0.6) < 1e-6  # (0.4+0.6+0.8)/3

    def test_competitors_surface_confidence(self):
        win = [_frame(t, [_trc(1, 0.5, 0.42)]) for t in (0, 1, 2)]
        comp = _competitors(_stable_tracks(win), {})
        assert comp and comp[0]["conf"] == 0.42


class TestWeakSubjectEscalation:
    """#7b: a sole LOW-confidence face may be a logo/title card (rf-udcpl2hd)."""

    def test_low_conf_sole_face_escalates_graphic(self):
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

    def test_high_conf_sole_face_does_not_escalate(self):
        tracked = [_frame(t, [_trc(1, 0.48, 0.95, w=0.31)]) for t in (0, 1, 2, 3)]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0)
        assert collect_escalation_points(plan) == []

    def test_gemini_subject_hint_suppresses_graphic_escalation(self):
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

    def test_two_faces_one_weak_uses_subject_path_not_graphic(self):
        # The graphic check is for a SOLE face; ≥2 faces stay on the subject path.
        tracked = [
            _frame(t, [_trc(1, 0.3, 0.35, w=0.2), _trc(2, 0.7, 0.4, w=0.2)])
            for t in (0, 1, 2, 3)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=4.0)
        kinds = {p["kind"] for p in collect_escalation_points(plan)}
        assert "weak_subject" not in kinds

    def test_threshold_constant_is_sane(self):
        assert 0.3 < FACE_CONF_MIN < 0.9


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


class TestSegmentTextBand:
    # _segment_text_band is the live measured-band accessor: median coverage + span
    # over the already-windowed text frames (reconcile bisect-slices per segment).
    def test_persistent_text_returns_median(self):
        win = [_txt(t, 0.8) for t in range(5)]
        cov, (x0, x1) = _segment_text_band(win)
        assert abs(cov - 0.8) < 1e-9
        assert x0 == 0.05 and abs(x1 - 0.85) < 1e-9

    def test_transient_flash_rejected(self):
        # One wide frame out of five → below the persistence floor → 0.
        win = [_txt(0, 0.9)] + [_txt(t, 0.0) for t in range(1, 5)]
        assert _segment_text_band(win) == (0.0, (0.0, 0.0))

    def test_empty_is_zero(self):
        assert _segment_text_band([]) == (0.0, (0.0, 0.0))


class TestReconcileWithText:
    # RETIRED floor: a wide measured text band never self-letterboxes. The CPU
    # can't tell a caption from a busy background, so it crops tight (fallback) and
    # ESCALATES the call to gemini-3.5-flash (Pass 2 applies any letterbox).
    def test_measured_wide_text_escalates(self):
        # No faces + a full-width band → tight crop (fallback) plus an escalation.
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
        assert tuple(plan[0]["inner_ar"]) == (9, 16)
        pts = collect_escalation_points(plan)
        assert pts and pts[0]["kind"] == "text_presence"

    def test_dominant_face_with_wide_text_escalates(self):
        # Centered talking head every frame + a wide CPU band → crop tight to the
        # speaker (fallback) and escalate; never self-letterbox over the speaker.
        tracked = [_frame(t, [_tr(1, 0.5, w=0.15)]) for t in (0, 2, 4)]
        text_frames = [_txt(t, 0.85) for t in range(6)]
        plan = reconcile(
            [],
            tracked,
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=6.0,
            text_frames=text_frames,
        )
        assert tuple(plan[0]["inner_ar"]) == (9, 16)
        assert plan[0]["escalate"]["kind"] == "text_presence"

    def test_no_wide_band_no_escalation(self):
        # No persistent wide band → no conflict, no Gemini call.
        tracked = [_frame(t, [_tr(1, 0.5, w=0.15)]) for t in (0, 2, 4)]
        text_frames = [_txt(t, 0.0) for t in range(6)]
        plan = reconcile(
            [],
            tracked,
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=6.0,
            text_frames=text_frames,
        )
        assert tuple(plan[0]["inner_ar"]) == (9, 16)
        assert not collect_escalation_points(plan)

    def test_requires_full_width_no_longer_refines(self):
        # RETIRED: Gemini requires_full_width is ignored; a measured 0.6 band only
        # escalates (fallback tight) — it does not drive a rung by itself.
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
        assert tuple(plan[0]["inner_ar"]) == (9, 16)


# ---------------------------------------------------------------------------
# Vertical-split layout (Phase 3): static, far-apart two-person dialogue
# ---------------------------------------------------------------------------


def _split_scene(scene_type="dialogue", layout=None):
    s = {
        "start_sec": 0,
        "end_sec": 5,
        "scene_type": scene_type,
        "active_subject": "both",
    }
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


class TestDialogueFromDiarization:
    """Without any Gemini scene, the diarization signal must still unlock split."""

    def _frames(self, x1=0.25, x2=0.75, n=5):
        # Far-apart, static, persistent; neither mouth clearly dominates.
        return [_ftrm(t, [(1, x1, 0.2), (2, x2, 0.2)]) for t in range(n)]

    def _two_speakers(self):
        return [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]

    def test_diarization_dialogue_centers_active_speaker(self):
        # Speaker-centering now takes precedence over split: a two-speaker dialogue
        # re-cuts at the turn and centers whoever is talking (single crop) instead of
        # stacking both. Each turn carries an active_speaker escalation keyed by the
        # dominant speaker, so the turns stay distinct. The 1 fps mouth signal can't
        # reliably tell a talker from a poster, so the escalation always fires for
        # multi-person speech and Gemini resolves it (follow a speaker, or letterbox
        # if it's a graphic); fallback = most-visible.
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=4.0,
            speaker_segments=self._two_speakers(),
        )
        assert all(seg["layout"] == "single" for seg in plan)
        # re-cut at the A→B turn (t=2.0) keeps two distinctly-keyed speaker segments
        assert len(plan) == 2
        kinds = [p["escalate"]["kind"] for p in plan if p.get("escalate")]
        assert kinds == ["active_speaker", "active_speaker"]
        # the escalation offers Gemini the poster escape (letterbox) too
        assert "letterbox" in plan[0]["escalate"]["question"].lower()

    def test_single_speaker_does_not_split(self):
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=4.0,
            speaker_segments=[
                {"speaker_id": "A", "start_sec": 0.0, "end_sec": 4.0},
            ],
        )
        assert plan[0]["layout"] != "split"

    def test_no_diarization_does_not_split(self):
        # No speaker_segments at all (e.g. silent video) → no dialogue intent.
        plan = reconcile(
            [], self._frames(), cuts=[], src_w=1920, src_h=1080, duration=4.0
        )
        assert plan[0]["layout"] != "split"

    def test_brief_second_speaker_is_not_dialogue(self):
        # A < DIALOGUE_MIN_SPEAK interjection by speaker B shouldn't flip to split.
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=4.0,
            speaker_segments=[
                {"speaker_id": "A", "start_sec": 0.0, "end_sec": 3.8},
                {"speaker_id": "B", "start_sec": 3.8, "end_sec": 4.0},
            ],
        )
        assert plan[0]["layout"] != "split"


class TestDialogueWindow:
    def test_two_speakers_taking_turns(self):
        from reframe_plan import _dialogue_in_window

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]
        assert _dialogue_in_window(segs, 0.0, 4.0) is True

    def test_overlap_clipped_to_window(self):
        from reframe_plan import _dialogue_in_window

        # B only overlaps the window by 0.2s (< DIALOGUE_MIN_SPEAK) → not dialogue.
        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 5.0},
            {"speaker_id": "B", "start_sec": 4.8, "end_sec": 9.0},
        ]
        assert _dialogue_in_window(segs, 0.0, 5.0) is False

    def test_empty_is_false(self):
        from reframe_plan import _dialogue_in_window

        assert _dialogue_in_window([], 0.0, 5.0) is False
        assert _dialogue_in_window(None or [], 0.0, 5.0) is False


class TestSpeakerCentering:
    """Multi-person → center the active speaker (audio↔face + Gemini fallback)."""

    TALK = [0.10, 0.45, 0.10, 0.50, 0.12]  # mouth oscillates → speaking
    STILL = [0.20, 0.21, 0.20, 0.19, 0.20]  # ~steady → listening

    def _frames(self, talker_x=0.3, other_x=0.7, both_talk=False):
        other = self.TALK if both_talk else self.STILL
        return [
            _ftrm(t, [(1, talker_x, self.TALK[t]), (2, other_x, other[t])])
            for t in range(5)
        ]

    def _one_speaker(self):
        return [{"speaker_id": "A", "start_sec": 0.0, "end_sec": 5.0}]

    def test_associate_picks_mouth_mover_during_speech(self):
        from reframe_plan import _associate_speaker_face

        win = self._frames()
        assert _associate_speaker_face(_stable_tracks(win), win, [(0.0, 5.0)]) == 1

    def test_associate_none_without_speech(self):
        # No diarized speech → mouth motion isn't anchored → no audio-visual pick.
        from reframe_plan import _associate_speaker_face

        win = self._frames()
        assert _associate_speaker_face(_stable_tracks(win), win, []) is None

    def test_associate_none_when_both_move(self):
        from reframe_plan import _associate_speaker_face

        win = self._frames(both_talk=True)
        assert _associate_speaker_face(_stable_tracks(win), win, [(0.0, 5.0)]) is None

    def test_centers_speaker_when_audio_visual_clear(self):
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=5.0,
            speaker_segments=self._one_speaker(),
        )
        crop = plan[0]["crops"][0]
        assert crop["source"] == "speaker" and crop["track_id"] == 1
        assert plan[0].get("escalate") is None  # resolved deterministically

    def test_escalates_active_speaker_when_ambiguous(self):
        # Both mouths move during speech → CPU can't tell → escalate; center the
        # most-visible face as the deterministic fallback.
        plan = reconcile(
            [],
            self._frames(both_talk=True),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=5.0,
            speaker_segments=self._one_speaker(),
        )
        seg = plan[0]
        assert seg["layout"] == "single"
        assert seg["escalate"]["kind"] == "active_speaker"
        assert seg["escalate"]["fallback"]["action"] == "follow"
        assert "candidates" in seg["escalate"]["facts"]


class TestSpeakerTurnCuts:
    def test_cuts_at_speaker_change(self):
        from reframe_plan import _speaker_turn_cuts

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 3.0},
            {"speaker_id": "B", "start_sec": 3.0, "end_sec": 6.0},
        ]
        assert _speaker_turn_cuts(segs, 1.8) == [3.0]

    def test_rapid_alternation_does_not_overfragment(self):
        from reframe_plan import _speaker_turn_cuts

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 0.5},
            {"speaker_id": "B", "start_sec": 0.5, "end_sec": 1.0},
            {"speaker_id": "A", "start_sec": 1.0, "end_sec": 4.0},
        ]
        assert _speaker_turn_cuts(segs, 1.8) == []  # all turns within min dwell

    def test_empty(self):
        from reframe_plan import _speaker_turn_cuts

        assert _speaker_turn_cuts([], 1.8) == []
        assert _speaker_turn_cuts(None, 1.8) == []

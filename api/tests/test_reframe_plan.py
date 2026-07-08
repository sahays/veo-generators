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

    def test_always_returns_the_ideal_rung(self):
        # Temporal damping is assign_rungs' job now — pick_rung is purely the
        # per-segment ideal.
        assert pick_rung(0.40, SRC_W, SRC_H) == (4, 5)
        assert pick_rung(0.10, SRC_W, SRC_H) == (9, 16)


class TestPickRung34:
    """3:4 is an adaptive ladder: full-bleed (3,4) then looser rungs that
    letterbox wide content — mirrors 9:16 on the shorter 1080x1440 canvas."""

    R34 = RUNGS_BY_CANVAS["3:4"]

    def test_ladder_full_bleed_then_looser(self):
        assert self.R34 == [(3, 4), (1, 1), (16, 9)]
        assert self.R34[0] == (3, 4)  # tightest rung = full-bleed, matches canvas
        covs = [rung_coverage(r, SRC_W, SRC_H) for r in self.R34]
        assert covs == sorted(covs)  # tightest → loosest

    def test_narrow_subject_picks_full_bleed(self):
        # A subject that fits the (3,4) crop (keeps ~0.42 of width) never letterboxes.
        for req in (0.0, 0.2, 0.42):
            assert pick_rung(req, SRC_W, SRC_H, rungs=self.R34) == (3, 4)

    def test_wide_content_letterboxes(self):
        # A two-shot needing ~0.55 width can't fit (3,4) → step to (1,1); a
        # genuinely full-width shot goes to (16,9). This is the crux of "adaptive".
        assert pick_rung(0.55, SRC_W, SRC_H, rungs=self.R34) == (1, 1)
        assert pick_rung(0.95, SRC_W, SRC_H, rungs=self.R34) == (16, 9)

    def test_dp_widens_wide_cells_never_crops_below_requirement(self):
        from reframe_plan import assign_rungs
        from reframe_rungs import RUNG_TOLERANCE

        cells = [
            {"C": c, "dur": 3.0, "starts_at_cut": True, "split": False}
            for c in (0.2, 0.9, 0.5)
        ]
        out = assign_rungs(cells, SRC_W, SRC_H, self.R34)
        assert out[0] == (3, 4)  # narrow → full-bleed, no bars
        assert out[1] == (16, 9)  # very wide → full-width letterbox
        # The rung guarantee: every chosen rung covers its cell's requirement.
        for cell, rung in zip(cells, out):
            assert rung_coverage(rung, SRC_W, SRC_H) + RUNG_TOLERANCE >= cell["C"]


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
        # cov < TEXT_WIDE_MIN (0.30): not a significant band.
        assert self._esc(0.05, 0.95, cov=0.2) is None

    def test_narrow_caption_escalates(self):
        # A 35%-wide lower-third at the frame edge is real information — it must
        # reach Gemini (the old 0.50 floor silently cropped it).
        e = self._esc(0.02, 0.37, cov=0.35)
        assert e is not None and e["facts"]["check_side"] == "left"

    def test_facts_carry_measured_band(self):
        # apply_verdicts falls back to the measured coverage when the model
        # omits `coverage` — the fact must actually be populated.
        e = self._esc(0.05, 0.90, cov=0.85)
        assert e["facts"]["text_coverage"] == 0.85
        assert e["facts"]["band"] == [0.05, 0.90]

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


class TestMergeShortContentGates:
    """A sub-dwell fold must never cross a content change (a <2s title card after
    a talking head used to inherit the speaker's crop and lose its escalation)."""

    def _seg(self, start, end, nf, esc=None, ar=(9, 16)):
        return {
            "start": start,
            "end": end,
            "inner_ar": ar,
            "layout": "single",
            "crops": [{"track_id": 1 if nf else None, "x_target": 0.5}],
            "trace": {"n_faces": nf},
            "reason": "",
            "escalate": esc,
        }

    def _graphic_esc(self, t=5.0):
        return {"kind": "no_subject", "key": f"nosubj:{t}"}

    def test_short_graphic_not_folded_into_speaker(self):
        # 1.5s no-face graphic after a 5s face shot: content differs → standalone.
        segs = [
            self._seg(0, 5, 1),
            self._seg(5, 6.5, 0, esc=self._graphic_esc()),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 2
        assert out[1]["escalate"]["kind"] == "no_subject"  # escalation survives

    def test_short_graphic_folds_forward_into_matching_shot(self):
        # 1.5s graphic cell then a longer cell of the SAME graphic (both no-face,
        # both no_subject): the short slice folds forward, not backward across
        # the cut into the speaker.
        segs = [
            self._seg(0, 5, 1),
            self._seg(5, 6.5, 0, esc=self._graphic_esc(5.0)),
            self._seg(6.5, 11, 0, esc=self._graphic_esc(6.5)),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 2
        assert out[1]["start"] == 5 and out[1]["end"] == 11
        assert out[1]["escalate"] is not None

    def test_forward_fold_keeps_looser_rung(self):
        # The folded short slice needed a looser rung — never crop it out.
        segs = [
            self._seg(0, 5, 1),
            self._seg(5, 6.5, 0, esc=self._graphic_esc(5.0), ar=(16, 9)),
            self._seg(6.5, 11, 0, esc=self._graphic_esc(6.5), ar=(9, 16)),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 2
        assert out[1]["inner_ar"] == (16, 9)

    def test_escalation_not_overwritten_by_folded_slice(self):
        # Prev keeps its own escalation when the folded compatible slice has the
        # same signature (no_subject folds by kind).
        segs = [
            self._seg(0, 5, 0, esc=self._graphic_esc(0.0)),
            self._seg(5, 6.5, 0, esc=self._graphic_esc(5.0)),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1
        assert out[0]["escalate"]["key"] == "nosubj:0.0"

    def test_short_speaker_cell_still_folds_backward(self):
        # Content-compatible sub-dwell folds keep the old behavior.
        segs = [self._seg(0, 5, 1), self._seg(5, 6.5, 1)]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1 and out[0]["end"] == 6.5

    def test_mid_shot_detector_dropout_bridges(self):
        # A sub-dwell "no detection" slice whose boundary is NOT a real cut is
        # the detector dropping the face for a beat, not a real cutaway — it
        # folds into its own shot despite the face↔no-face change (rf-udcpl2hd).
        segs = [self._seg(0, 5, 1), self._seg(5, 5.7, 0, esc=self._graphic_esc())]
        segs[1]["starts_at_cut"] = False  # subdivision / turn boundary, same shot
        out = _merge_short(segs, 2.0)
        assert len(out) == 1 and out[0]["end"] == 5.7
        # ...and the speaker shot keeps its own framing (n_faces stays 1)
        assert out[0]["trace"]["n_faces"] == 1


class TestRungDP:
    """Global rung assignment: flip-flops damped, no chaining, mid-shot stable."""

    def _cells(self, spec):
        # spec: list of (required_coverage, dur, starts_at_cut)
        return [
            {"C": c, "dur": d, "starts_at_cut": cut, "split": False}
            for c, d, cut in spec
        ]

    def test_sustained_waste_retightens_at_the_cut(self):
        # Wide shot then two long narrow shots: no reason to hold 4:5 — bars
        # come off at the first cut (the ashley-trip chain, dead by construction).
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.42, 5, True), (0.2, 5, True), (0.2, 5, True)]),
            SRC_W,
            SRC_H,
        )
        assert got == [(4, 5), (9, 16), (9, 16)]

    def test_true_flip_flop_is_damped(self):
        # A-B-A shot pattern with a SHORT middle shot: holding 4:5 through it
        # avoids bars popping off and back on within two seconds.
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.42, 5, True), (0.2, 2, True), (0.42, 5, True)]),
            SRC_W,
            SRC_H,
        )
        assert got == [(4, 5), (4, 5), (4, 5)]

    def test_mid_shot_widening_beats_bar_pops(self):
        # One long take subdivided into cells; the middle cell needs 4:5 (two
        # faces walk in). Changing bars twice MID-SHOT is worse than holding
        # the whole take at 4:5.
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.2, 5, True), (0.42, 2, False), (0.2, 5, False)]),
            SRC_W,
            SRC_H,
        )
        assert got == [(4, 5), (4, 5), (4, 5)]

    def test_coverage_is_never_sacrificed(self):
        # A cell whose content needs full width must get 16:9 regardless of
        # what stability would prefer.
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.2, 5, True), (0.95, 2, False), (0.2, 5, False)]),
            SRC_W,
            SRC_H,
        )
        assert got[1] == (16, 9)

    def test_split_cells_break_the_chain(self):
        from reframe_plan import assign_rungs

        cells = self._cells([(0.42, 5, True), (0.2, 5, True)])
        cells.insert(1, {"C": 1.0, "dur": 4, "starts_at_cut": True, "split": True})
        got = assign_rungs(cells, SRC_W, SRC_H)
        assert got[1] is None
        assert got[2] == (9, 16)  # no transition pressure across the split

    def test_reconcile_end_to_end_no_chaining(self):
        # Same scenario as the old greedy-hysteresis chain test, through the
        # full planner: the wide shot's rung must not leak past the next cut.
        tracked = (
            [_frame(float(t), [_tr(1, 0.35), _tr(2, 0.62)]) for t in range(0, 5)]
            + [_frame(float(t), [_tr(3, 0.5)]) for t in range(5, 10)]
            + [_frame(float(t), [_tr(4, 0.5)]) for t in range(10, 15)]
        )
        plan = reconcile(
            [], tracked, cuts=[5.0, 10.0], src_w=SRC_W, src_h=SRC_H, duration=15.0
        )
        assert plan[0]["inner_ar"] == (4, 5)  # earned: two-face span
        assert all(s["inner_ar"] == (9, 16) for s in plan[1:])  # no leak


class TestBoundaryHairlines:
    def test_coincident_cuts_do_not_make_subframe_cells(self):
        # A scene cut and a speaker-turn cut microseconds apart → one boundary.
        bounds = _boundaries([3.6, 3.6004], 10.0)
        assert all((e - s) > 0.05 for s, e in bounds), bounds

    def test_cut_next_to_video_end_dropped(self):
        bounds = _boundaries([9.97], 10.0)
        assert bounds[-1][1] == 10.0
        assert all((e - s) > 0.05 for s, e in bounds), bounds


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
        # Comparably PRESENT but differently SIZED faces (not an equal pair),
        # neither clearly speaking → the single-subject pick is ambiguous →
        # escalate which-subject (#3/#4) to gemini-3.5.
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.05)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        pts = collect_escalation_points(plan)
        assert any(p["kind"] == "subject_choice" for p in pts)

    def test_two_equal_faces_keep_both(self):
        # PRODUCT RULE: equally present AND equally sized people are framed
        # together — no single-subject pick, no escalation needed.
        tracked = [
            _frame(t, [_tr(1, 0.45, w=0.12), _tr(2, 0.55, w=0.12)]) for t in (0, 2, 4)
        ]
        plan = reconcile([], tracked, cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0)
        assert plan[0]["layout"] == "keep_both"
        assert plan[0]["crops"][0]["track_ids"] == [1, 2]
        assert not collect_escalation_points(plan)

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
    # specs: list of (track_id, x, mouth[, w])
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

    def test_equal_pair_keeps_both_despite_clear_talker(self):
        # PRODUCT RULE: equally prominent people are framed together even when
        # one clearly talks — never push the equal listener out of frame.
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
        assert plan[0]["layout"] in ("keep_both", "split")

    def test_reconcile_frames_speaker_when_listener_smaller(self):
        # A clearly-smaller background face is NOT an equal pair → follow the
        # talker as before.
        frames = [
            _ftrm(t, [(1, 0.30, self.TALK[t], 0.12), (2, 0.70, self.STILL[t], 0.05)])
            for t in range(5)
        ]
        scenes = [
            {
                "start_sec": 0,
                "end_sec": 5,
                "scene_type": "general",
                "active_subject": "left",
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

    def test_close_together_is_keep_both_not_split(self):
        # An equal close pair: one tight crop holds both (keep_both on the
        # tightest rung) — stacking would be pointless.
        plan = self._plan(self._frames(x1=0.45, x2=0.55), _split_scene())
        assert plan[0]["layout"] == "keep_both"
        assert plan[0]["inner_ar"] == (9, 16)  # span fits the full-bleed rung

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

    def test_dominant_speaker_on_equal_pair_still_frames_both(self):
        # PRODUCT RULE: a clear talker does not excuse losing an equally
        # prominent listener — the equal pair splits (gates pass here).
        talk = [0.10, 0.45, 0.10, 0.50, 0.12]
        frames = [_ftrm(t, [(1, 0.25, talk[t]), (2, 0.75, 0.2)]) for t in range(5)]
        seg = self._plan(frames, _split_scene())[0]
        assert seg["layout"] == "split"

    def test_dominant_speaker_follows_when_listener_smaller(self):
        # Not an equal pair (listener clearly smaller) → follow the talker.
        talk = [0.10, 0.45, 0.10, 0.50, 0.12]
        frames = [
            _ftrm(t, [(1, 0.25, talk[t], 0.12), (2, 0.75, 0.2, 0.05)]) for t in range(5)
        ]
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

    def test_diarization_dialogue_keeps_equal_pair_together(self):
        # PRODUCT RULE: an equal two-person dialogue is framed together
        # (keep-both / split), not speaker-centered per turn — a centered crop
        # would push the equally-prominent listener out of frame during every
        # other turn. Identical turn cells re-merge into one steady segment.
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=4.0,
            speaker_segments=self._two_speakers(),
        )
        assert all(seg["layout"] in ("keep_both", "split") for seg in plan)
        assert len(plan) == 1  # same framing across the turn → merged back
        assert not collect_escalation_points(plan)

    def test_diarization_dialogue_unequal_pair_escalates_speaker(self):
        # A dialogue where the second face is clearly smaller still runs the
        # speaker machinery: escalate per turn (mouths ambiguous at 0.2 const),
        # offering the poster escape (letterbox) too.
        frames = [
            _ftrm(t, [(1, 0.25, 0.2, 0.12), (2, 0.75, 0.2, 0.05)]) for t in range(5)
        ]
        plan = reconcile(
            [],
            frames,
            cuts=[],
            src_w=1920,
            src_h=1080,
            duration=4.0,
            speaker_segments=self._two_speakers(),
        )
        assert all(seg["layout"] == "single" for seg in plan)
        assert len(plan) == 2  # re-cut at the A→B turn keeps distinct keys
        kinds = [p["escalate"]["kind"] for p in plan if p.get("escalate")]
        assert kinds == ["active_speaker", "active_speaker"]
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

    def _frames(self, talker_x=0.3, other_x=0.7, both_talk=False, other_w=0.05):
        # Listener smaller by default so these exercise the SPEAKER path (an
        # equal pair is framed together by the equal-prominence product rule).
        other = self.TALK if both_talk else self.STILL
        return [
            _ftrm(
                t, [(1, talker_x, self.TALK[t], 0.12), (2, other_x, other[t], other_w)]
            )
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


class TestSpeakerEscalationOffersKeepBoth:
    """#4 must offer keep_both/split when the two-shot geometry supports them —
    otherwise a wide two-person conversation (which always has speech) could
    only ever be answered with one centered person or a letterbox.

    Faces here are UNEQUAL sizes: an equal pair is framed together
    deterministically (equal-prominence rule) and never escalates."""

    def _frames(self, x1=0.25, x2=0.75, n=5):
        return [_ftrm(t, [(1, x1, 0.2, 0.12), (2, x2, 0.2, 0.05)]) for t in range(n)]

    def _two_speakers(self):
        return [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]

    def test_far_apart_pair_offers_keep_both(self):
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            speaker_segments=self._two_speakers(),
        )
        esc = plan[0]["escalate"]
        assert esc["kind"] == "active_speaker"
        assert esc["facts"].get("can_keep_both") is True
        assert sorted(esc["facts"]["pair"]) == [1, 2]
        assert "keep_both" in esc["question"]
        # candidates carry measured widths so a keep_both verdict can size the span
        assert all("w" in c for c in esc["facts"]["candidates"])

    def test_moderate_separation_offers_keep_both_without_dialogue_label(self):
        # sep ≈ 0.32: above KEEP_BOTH_SEPARATION but below the 0.45 no-label bar.
        # The OFFER must not need the intent gate — Gemini judges intent from
        # pixels (rf-udcpl2hd lost the second person entirely at sep 0.32).
        plan = reconcile(
            [],
            self._frames(x1=0.34, x2=0.66),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            speaker_segments=[
                {"speaker_id": "A", "start_sec": 0.0, "end_sec": 4.0}
            ],  # one speaker → no dialogue label
        )
        esc = plan[0]["escalate"]
        assert esc["kind"] == "active_speaker"
        assert esc["facts"].get("can_keep_both") is True

    def test_coexisting_text_band_folds_into_speaker_question(self):
        # A caption AND a speaker ambiguity in the same segment: the speaker
        # escalation replaces the text one, so it must carry the text conflict
        # itself — else Gemini is never told text is at stake and a press quote
        # gets cropped (observed on rf-udcpl2hd at 5.9-12.9s).
        text_frames = [_txt(t * 0.5, 0.8) for t in range(8)]
        plan = reconcile(
            [],
            self._frames(),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            speaker_segments=self._two_speakers(),
            text_frames=text_frames,
        )
        esc = plan[0]["escalate"]
        assert esc["kind"] == "active_speaker"
        assert esc["facts"]["text_coverage"] == 0.8
        assert "band" in esc["facts"]
        assert "readable text" in esc["question"]

    def test_close_pair_does_not_offer_keep_both(self):
        plan = reconcile(
            [],
            self._frames(x1=0.45, x2=0.55),
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=4.0,
            speaker_segments=self._two_speakers(),
        )
        esc = plan[0]["escalate"]
        assert esc["kind"] == "active_speaker"
        assert "can_keep_both" not in esc["facts"]
        assert "keep_both" not in esc["question"]


class TestCandidateLabels:
    def test_distinct_buckets_kept(self):
        from reframe_plan import _candidate_labels

        assert _candidate_labels([{"x": 0.2}, {"x": 0.8}]) == ["left", "right"]

    def test_two_center_faces_disambiguated(self):
        from reframe_plan import _candidate_labels

        # Both bucket to "center" → a `subject=center` verdict would be ambiguous.
        assert _candidate_labels([{"x": 0.45}, {"x": 0.55}]) == ["left", "right"]

    def test_three_clustered_faces_ranked(self):
        from reframe_plan import _candidate_labels

        got = _candidate_labels([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}])
        assert got == ["left", "center", "right"]


class TestPanContinuity:
    """Adjacent cells of the same shot must pan, not jump, at their boundary."""

    def _drifting_track(self):
        # One track that sits at 0.2 for the first cell and 0.8 for the second —
        # a slow reposition a per-cell median lock would turn into a hard jump.
        return [_frame(float(t), [_tr(1, 0.2 if t < 5 else 0.8)]) for t in range(10)]

    def test_mid_shot_boundary_pans_from_previous_x(self):
        plan = reconcile(
            [], self._drifting_track(), cuts=[], src_w=SRC_W, src_h=SRC_H, duration=10.0
        )
        assert len(plan) == 2  # x differs beyond MERGE_X_TOL → separate cells
        assert plan[1]["starts_at_cut"] is False  # subdivision, not a real cut
        attach_keypoints(plan, fps=30)
        end_x = plan[0]["crops"][0]["keypoints"][-1][1]
        kps = plan[1]["crops"][0]["keypoints"]
        assert abs(kps[0][1] - end_x) < 0.02  # starts where the last cell ended
        assert abs(kps[-1][1] - 0.8) < 0.05  # ...and still reaches its target

    def test_real_cut_reframes_hard(self):
        plan = reconcile(
            [],
            self._drifting_track(),
            cuts=[5.0],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=10.0,
        )
        assert len(plan) == 2
        assert plan[1]["starts_at_cut"] is True
        attach_keypoints(plan, fps=30)
        kps = plan[1]["crops"][0]["keypoints"]
        assert abs(kps[0][1] - 0.8) < 0.05  # no seeding across a scene cut


class TestAdaptive34EscalatesLikeMultiRung:
    """3:4 is now a multi-rung adaptive ladder (can_letterbox=True), so it emits
    the SAME letterbox escalations as 9:16 — wide text/graphics are Gemini's call
    to preserve, not silently cropped."""

    R34 = RUNGS_BY_CANVAS["3:4"]
    R916 = RUNGS_BY_CANVAS["9:16"]

    def _kinds(self, rungs, **kw):
        plan = reconcile(
            [], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0, rungs=rungs, **kw
        )
        return sorted(p["kind"] for p in collect_escalation_points(plan))

    def test_no_subject_escalates_like_9x16(self):
        assert self._kinds(self.R34) == self._kinds(self.R916) == ["no_subject"]

    def test_wide_text_escalates_like_9x16(self):
        text_frames = [_txt(t, 0.9) for t in range(6)]
        assert (
            self._kinds(self.R34, text_frames=text_frames)
            == self._kinds(self.R916, text_frames=text_frames)
            == ["text_presence"]
        )

    def test_speaker_escalation_still_fires(self):
        # A `follow` verdict re-targets the crop — useful on any ladder.
        # (Unequal sizes: an equal pair keeps both deterministically instead.)
        frames = [
            _ftrm(t, [(1, 0.3, 0.2, 0.12), (2, 0.7, 0.2, 0.05)]) for t in range(5)
        ]
        plan = reconcile(
            [],
            frames,
            cuts=[],
            src_w=SRC_W,
            src_h=SRC_H,
            duration=5.0,
            rungs=self.R34,
            speaker_segments=[{"speaker_id": "A", "start_sec": 0.0, "end_sec": 5.0}],
        )
        kinds = {p["kind"] for p in collect_escalation_points(plan)}
        assert kinds == {"active_speaker"}


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

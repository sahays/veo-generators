"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_plan import (
    RUNGS,
    RUNGS_BY_CANVAS,
    _boundaries,
    _global_label_map,
    _keep_both_pair,
    _match_track,
    _maybe_subject_escalation,
    _maybe_text_escalation,
    _merge_short,
    _motion_scene_type,
    _side_of,
    pick_rung,
    reconcile,
    rung_coverage,
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
# Rung math
# ---------------------------------------------------------------------------


class TestRungCoverage:
    def test_ladder_is_monotonic(self) -> None:
        covs = [rung_coverage(r, SRC_W, SRC_H) for r in RUNGS]
        assert covs == sorted(covs)  # tightest → loosest

    def test_known_values(self) -> None:
        assert abs(rung_coverage((9, 16), SRC_W, SRC_H) - 0.316) < 0.01
        assert abs(rung_coverage((1, 1), SRC_W, SRC_H) - 0.5625) < 0.01
        assert rung_coverage((16, 9), SRC_W, SRC_H) == 1.0  # clamped


class TestPickRung:
    def test_narrow_subject_picks_tightest(self) -> None:
        assert pick_rung(0.15, SRC_W, SRC_H) == (9, 16)

    def test_wide_subject_picks_looser(self) -> None:
        assert pick_rung(0.54, SRC_W, SRC_H) == (1, 1)

    def test_full_width_picks_letterbox(self) -> None:
        assert pick_rung(0.99, SRC_W, SRC_H) == (16, 9)

    def test_tolerance_prefers_tighter_near_boundary(self) -> None:
        # 0.60 is just above 1:1's 0.5625 — tolerance keeps it at 1:1, not 16:9.
        assert pick_rung(0.60, SRC_W, SRC_H) == (1, 1)
        # but a genuinely wide requirement still letterboxes
        assert pick_rung(0.75, SRC_W, SRC_H) == (16, 9)

    def test_always_returns_the_ideal_rung(self) -> None:
        # Temporal damping is assign_rungs' job now — pick_rung is purely the
        # per-segment ideal.
        assert pick_rung(0.40, SRC_W, SRC_H) == (4, 5)
        assert pick_rung(0.10, SRC_W, SRC_H) == (9, 16)


class TestPickRung34:
    """3:4 is an adaptive ladder: full-bleed (3,4) then looser rungs that
    letterbox wide content — mirrors 9:16 on the shorter 1080x1440 canvas."""

    R34 = RUNGS_BY_CANVAS["3:4"]

    def test_ladder_full_bleed_then_looser(self) -> None:
        assert self.R34 == [(3, 4), (1, 1), (16, 9)]
        assert self.R34[0] == (3, 4)  # tightest rung = full-bleed, matches canvas
        covs = [rung_coverage(r, SRC_W, SRC_H) for r in self.R34]
        assert covs == sorted(covs)  # tightest → loosest

    def test_narrow_subject_picks_full_bleed(self) -> None:
        # A subject that fits the (3,4) crop (keeps ~0.42 of width) never letterboxes.
        for req in (0.0, 0.2, 0.42):
            assert pick_rung(req, SRC_W, SRC_H, rungs=self.R34) == (3, 4)

    def test_wide_content_letterboxes(self) -> None:
        # A two-shot needing ~0.55 width can't fit (3,4) → step to (1,1); a
        # genuinely full-width shot goes to (16,9). This is the crux of "adaptive".
        assert pick_rung(0.55, SRC_W, SRC_H, rungs=self.R34) == (1, 1)
        assert pick_rung(0.95, SRC_W, SRC_H, rungs=self.R34) == (16, 9)

    def test_dp_widens_wide_cells_never_crops_below_requirement(self) -> None:
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
    def test_global_label_map_by_frequency(self) -> None:
        frames = [_frame(0, [_tr(7, 0.3), _tr(2, 0.7)]), _frame(2, [_tr(7, 0.3)])]
        lm = _global_label_map(frames)
        assert lm["A"] == 7  # most visible
        assert lm["B"] == 2

    def test_match_track_a_resolves_to_most_visible(self) -> None:
        stable = [
            {"track_id": 7, "x": 0.3, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.7, "w": 0.1, "frac": 0.5},
        ]
        lm = {"A": 7, "B": 2}
        got = _match_track(stable, {"active_subject": "Track A"}, lm)
        assert got["track_id"] == 7  # not the lowest track_id (the v1 bug)

    def test_match_left_right(self) -> None:
        stable = [
            {"track_id": 1, "x": 0.2, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.8, "w": 0.1, "frac": 1.0},
        ]
        assert _match_track(stable, {"active_subject": "right"}, {})["track_id"] == 2
        assert _match_track(stable, {"active_subject": "left"}, {})["track_id"] == 1


class TestKeepBothPair:
    def test_two_far_apart_dialogue(self) -> None:
        stable = [
            {"track_id": 1, "x": 0.3, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.7, "w": 0.1, "frac": 1.0},
        ]
        pair = _keep_both_pair(stable, {"scene_type": "dialogue"})
        assert pair is not None and len(pair) == 2

    def test_close_together_is_single(self) -> None:
        stable = [
            {"track_id": 1, "x": 0.48, "w": 0.1, "frac": 1.0},
            {"track_id": 2, "x": 0.52, "w": 0.1, "frac": 1.0},
        ]
        assert _keep_both_pair(stable, {"scene_type": "dialogue"}) is None

    def test_single_track_is_none(self) -> None:
        assert (
            _keep_both_pair([{"track_id": 1, "x": 0.5, "w": 0.1, "frac": 1.0}], {})
            is None
        )


# ---------------------------------------------------------------------------
# Merge / dwell
# ---------------------------------------------------------------------------


class TestTextEscalationPredicate:
    # subject at x=0.5 → tight 9:16 crop keeps ~[0.342, 0.658]; SIDE_TEXT_MARGIN=0.06.
    def _esc(self, x0: Any, x1: Any, cov: Any = 0.85, subj: Any = 0.5) -> Any:
        return _maybe_text_escalation(
            (cov, (x0, x1)), subj, 1, SRC_W, SRC_H, RUNGS, 0.0, 4.0
        )

    def test_band_inside_crop_window_no_escalation(self) -> None:
        # A band fully behind the subject (within the kept region) → nothing cut.
        assert self._esc(0.40, 0.62) is None

    def test_narrow_peripheral_band_escalates(self) -> None:
        # Significance is reach past the crop window, not total width: a caption
        # narrower than the old 0.30 floor but sitting outside the crop still gets
        # clipped, so it must reach Gemini (rf-r5eik9j2's ~0.28-wide side callouts).
        e = self._esc(0.02, 0.26, cov=0.24)
        assert e is not None and e["facts"]["check_side"] == "left"

    def test_narrow_caption_escalates(self) -> None:
        # A 35%-wide lower-third at the frame edge is real information — it must
        # reach Gemini (the old 0.50 floor silently cropped it).
        e = self._esc(0.02, 0.37, cov=0.35)
        assert e is not None and e["facts"]["check_side"] == "left"

    def test_facts_carry_measured_band(self) -> None:
        # apply_verdicts falls back to the measured coverage when the model
        # omits `coverage` — the fact must actually be populated.
        e = self._esc(0.05, 0.90, cov=0.85)
        assert e["facts"]["text_coverage"] == 0.85
        assert e["facts"]["band"] == [0.05, 0.90]

    def test_band_left_only(self) -> None:
        e = self._esc(0.05, 0.55)  # pokes past the left edge, not the right
        assert e is not None and e["facts"]["check_side"] == "left"

    def test_band_right_only(self) -> None:
        e = self._esc(0.45, 0.97)
        assert e is not None and e["facts"]["check_side"] == "right"

    def test_band_both_sides(self) -> None:
        e = self._esc(0.05, 0.97)
        assert e is not None and e["facts"]["check_side"] == "both"

    def test_margin_boundary_not_escalated(self) -> None:
        # Just within margin on each side (0.342-0.06=0.282 .. 0.658+0.06=0.718).
        assert self._esc(0.29, 0.71) is None

    def test_offcenter_subject_shifts_window(self) -> None:
        # Subject far left → a right-side band is now "cut", a left one isn't.
        e = self._esc(0.30, 0.95, subj=0.25)
        assert e is not None and e["facts"]["check_side"] == "right"


class TestSubjectEscalationPredicate:
    def _stable(self, *xf: Any) -> Any:
        return [
            {"track_id": i + 1, "x": x, "w": 0.12, "frac": f}
            for i, (x, f) in enumerate(xf)
        ]

    def test_single_face_no_escalation(self) -> None:
        st = self._stable((0.5, 1.0))
        assert _maybe_subject_escalation(st, st[0], 0.0, 4.0) is None

    def test_one_clearly_dominant_no_escalation(self) -> None:
        # 2nd face only 0.3 as present as the 1st (< SUBJECT_AMBIG_RATIO 0.6).
        st = self._stable((0.3, 1.0), (0.7, 0.3))
        assert _maybe_subject_escalation(st, st[0], 0.0, 4.0) is None

    def test_two_comparable_faces_escalate(self) -> None:
        st = self._stable((0.3, 1.0), (0.7, 0.9))
        e = _maybe_subject_escalation(st, st[0], 0.0, 4.0)
        assert e is not None and len(e["facts"]["candidates"]) == 2

    def test_side_of_buckets(self) -> None:
        assert (_side_of(0.2), _side_of(0.5), _side_of(0.8)) == (
            "left",
            "center",
            "right",
        )


class TestMotionSceneType:
    def _d(self, tid: Any) -> Any:
        return {"crops": [{"track_id": tid}]}

    def test_static_subject_is_general(self) -> None:
        win = [_frame(t, [_tr(1, 0.5)]) for t in range(4)]
        assert _motion_scene_type(self._d(1), win, []) == "general"

    def test_fast_moving_subject_is_action(self) -> None:
        win = [_frame(0, [_tr(1, 0.15)]), _frame(1, [_tr(1, 0.85)])]  # spread 0.7
        assert _motion_scene_type(self._d(1), win, []) == "action"

    def test_no_face_uses_person_spread(self) -> None:
        pf = [_pframe(0, [_person(0.1)]), _pframe(1, [_person(0.9)])]
        assert _motion_scene_type({"crops": [{"track_id": None}]}, [], pf) == "action"


class TestMergeShort:
    def _seg(self, start: Any, end: Any, ar: Any, layout: Any = "single") -> Any:
        return {
            "start": start,
            "end": end,
            "inner_ar": ar,
            "layout": layout,
            "crops": [{"track_id": 1, "x_target": 0.5}],
            "reason": "",
        }

    def test_collapses_identical_neighbors(self) -> None:
        segs = [self._seg(0, 5, (9, 16)), self._seg(5, 10, (9, 16))]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1 and out[0]["end"] == 10

    def test_folds_short_segment_into_prev_keeping_looser(self) -> None:
        segs = [self._seg(0, 5, (9, 16)), self._seg(5, 5.5, (1, 1))]  # 0.5s blip
        out = _merge_short(segs, 2.0)
        assert len(out) == 1
        assert out[0]["inner_ar"] == (1, 1)  # looser rung wins (never crop content)
        assert out[0]["end"] == 5.5


class TestMergeShortContentGates:
    """A sub-dwell fold must never cross a content change (a <2s title card after
    a talking head used to inherit the speaker's crop and lose its escalation)."""

    def _seg(
        self, start: Any, end: Any, nf: Any, esc: Any = None, ar: Any = (9, 16)
    ) -> Any:
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

    def _graphic_esc(self, t: Any = 5.0) -> Any:
        return {"kind": "no_subject", "key": f"nosubj:{t}"}

    def test_short_graphic_not_folded_into_speaker(self) -> None:
        # 1.5s no-face graphic after a 5s face shot: content differs → standalone.
        segs = [
            self._seg(0, 5, 1),
            self._seg(5, 6.5, 0, esc=self._graphic_esc()),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 2
        assert out[1]["escalate"]["kind"] == "no_subject"  # escalation survives

    def test_short_graphic_folds_forward_into_matching_shot(self) -> None:
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

    def test_forward_fold_keeps_looser_rung(self) -> None:
        # The folded short slice needed a looser rung — never crop it out.
        segs = [
            self._seg(0, 5, 1),
            self._seg(5, 6.5, 0, esc=self._graphic_esc(5.0), ar=(16, 9)),
            self._seg(6.5, 11, 0, esc=self._graphic_esc(6.5), ar=(9, 16)),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 2
        assert out[1]["inner_ar"] == (16, 9)

    def test_escalation_not_overwritten_by_folded_slice(self) -> None:
        # Prev keeps its own escalation when the folded compatible slice has the
        # same signature (no_subject folds by kind).
        segs = [
            self._seg(0, 5, 0, esc=self._graphic_esc(0.0)),
            self._seg(5, 6.5, 0, esc=self._graphic_esc(5.0)),
        ]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1
        assert out[0]["escalate"]["key"] == "nosubj:0.0"

    def test_short_speaker_cell_still_folds_backward(self) -> None:
        # Content-compatible sub-dwell folds keep the old behavior.
        segs = [self._seg(0, 5, 1), self._seg(5, 6.5, 1)]
        out = _merge_short(segs, 2.0)
        assert len(out) == 1 and out[0]["end"] == 6.5

    def test_mid_shot_detector_dropout_bridges(self) -> None:
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

    def _cells(self, spec: Any) -> Any:
        # spec: list of (required_coverage, dur, starts_at_cut)
        return [
            {"C": c, "dur": d, "starts_at_cut": cut, "split": False}
            for c, d, cut in spec
        ]

    def test_sustained_waste_retightens_at_the_cut(self) -> None:
        # Wide shot then two long narrow shots: no reason to hold 4:5 — bars
        # come off at the first cut (the ashley-trip chain, dead by construction).
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.42, 5, True), (0.2, 5, True), (0.2, 5, True)]),
            SRC_W,
            SRC_H,
        )
        assert got == [(4, 5), (9, 16), (9, 16)]

    def test_true_flip_flop_is_damped(self) -> None:
        # A-B-A shot pattern with a SHORT middle shot: holding 4:5 through it
        # avoids bars popping off and back on within two seconds.
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.42, 5, True), (0.2, 2, True), (0.42, 5, True)]),
            SRC_W,
            SRC_H,
        )
        assert got == [(4, 5), (4, 5), (4, 5)]

    def test_mid_shot_widening_beats_bar_pops(self) -> None:
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

    def test_coverage_is_never_sacrificed(self) -> None:
        # A cell whose content needs full width must get 16:9 regardless of
        # what stability would prefer.
        from reframe_plan import assign_rungs

        got = assign_rungs(
            self._cells([(0.2, 5, True), (0.95, 2, False), (0.2, 5, False)]),
            SRC_W,
            SRC_H,
        )
        assert got[1] == (16, 9)

    def test_split_cells_break_the_chain(self) -> None:
        from reframe_plan import assign_rungs

        cells = self._cells([(0.42, 5, True), (0.2, 5, True)])
        cells.insert(1, {"C": 1.0, "dur": 4, "starts_at_cut": True, "split": True})
        got = assign_rungs(cells, SRC_W, SRC_H)
        assert got[1] is None
        assert got[2] == (9, 16)  # no transition pressure across the split

    def test_reconcile_end_to_end_no_chaining(self) -> None:
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
    def test_coincident_cuts_do_not_make_subframe_cells(self) -> None:
        # A scene cut and a speaker-turn cut microseconds apart → one boundary.
        bounds = _boundaries([3.6, 3.6004], 10.0)
        assert all((e - s) > 0.05 for s, e in bounds), bounds

    def test_cut_next_to_video_end_dropped(self) -> None:
        bounds = _boundaries([9.97], 10.0)
        assert bounds[-1][1] == 10.0
        assert all((e - s) > 0.05 for s, e in bounds), bounds

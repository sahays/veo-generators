"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_plan import (
    RUNGS_BY_CANVAS,
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


class TestDialogueWindow:
    def test_two_speakers_taking_turns(self) -> None:
        from reframe_plan import _dialogue_in_window

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]
        assert _dialogue_in_window(segs, 0.0, 4.0) is True

    def test_overlap_clipped_to_window(self) -> None:
        from reframe_plan import _dialogue_in_window

        # B only overlaps the window by 0.2s (< DIALOGUE_MIN_SPEAK) → not dialogue.
        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 5.0},
            {"speaker_id": "B", "start_sec": 4.8, "end_sec": 9.0},
        ]
        assert _dialogue_in_window(segs, 0.0, 5.0) is False

    def test_empty_is_false(self) -> None:
        from reframe_plan import _dialogue_in_window

        assert _dialogue_in_window([], 0.0, 5.0) is False
        assert _dialogue_in_window(None or [], 0.0, 5.0) is False


class TestSpeakerCentering:
    """Multi-person → center the active speaker (audio↔face + Gemini fallback)."""

    TALK = [0.10, 0.45, 0.10, 0.50, 0.12]  # mouth oscillates → speaking
    STILL = [0.20, 0.21, 0.20, 0.19, 0.20]  # ~steady → listening

    def _frames(
        self,
        talker_x: Any = 0.3,
        other_x: Any = 0.7,
        both_talk: Any = False,
        other_w: Any = 0.05,
    ) -> Any:
        # Listener smaller by default so these exercise the SPEAKER path (an
        # equal pair is framed together by the equal-prominence product rule).
        other = self.TALK if both_talk else self.STILL
        return [
            _ftrm(
                t, [(1, talker_x, self.TALK[t], 0.12), (2, other_x, other[t], other_w)]
            )
            for t in range(5)
        ]

    def _one_speaker(self) -> Any:
        return [{"speaker_id": "A", "start_sec": 0.0, "end_sec": 5.0}]

    def test_associate_picks_mouth_mover_during_speech(self) -> None:
        from reframe_plan import _associate_speaker_face

        win = self._frames()
        assert _associate_speaker_face(_stable_tracks(win), win, [(0.0, 5.0)]) == 1

    def test_associate_none_without_speech(self) -> None:
        # No diarized speech → mouth motion isn't anchored → no audio-visual pick.
        from reframe_plan import _associate_speaker_face

        win = self._frames()
        assert _associate_speaker_face(_stable_tracks(win), win, []) is None

    def test_associate_none_when_both_move(self) -> None:
        from reframe_plan import _associate_speaker_face

        win = self._frames(both_talk=True)
        assert _associate_speaker_face(_stable_tracks(win), win, [(0.0, 5.0)]) is None

    def test_centers_speaker_when_audio_visual_clear(self) -> None:
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

    def test_escalates_active_speaker_when_ambiguous(self) -> None:
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

    def _frames(self, x1: Any = 0.25, x2: Any = 0.75, n: Any = 5) -> Any:
        return [_ftrm(t, [(1, x1, 0.2, 0.12), (2, x2, 0.2, 0.05)]) for t in range(n)]

    def _two_speakers(self) -> Any:
        return [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]

    def test_far_apart_pair_offers_keep_both(self) -> None:
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

    def test_moderate_separation_offers_keep_both_without_dialogue_label(self) -> None:
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

    def test_coexisting_text_band_folds_into_speaker_question(self) -> None:
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

    def test_close_pair_does_not_offer_keep_both(self) -> None:
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
    def test_distinct_buckets_kept(self) -> None:
        from reframe_plan import _candidate_labels

        assert _candidate_labels([{"x": 0.2}, {"x": 0.8}]) == ["left", "right"]

    def test_two_center_faces_disambiguated(self) -> None:
        from reframe_plan import _candidate_labels

        # Both bucket to "center" → a `subject=center` verdict would be ambiguous.
        assert _candidate_labels([{"x": 0.45}, {"x": 0.55}]) == ["left", "right"]

    def test_three_clustered_faces_ranked(self) -> None:
        from reframe_plan import _candidate_labels

        got = _candidate_labels([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}])
        assert got == ["left", "center", "right"]


class TestPanContinuity:
    """Adjacent cells of the same shot must pan, not jump, at their boundary."""

    def _drifting_track(self) -> Any:
        # One track that sits at 0.2 for the first cell and 0.8 for the second —
        # a slow reposition a per-cell median lock would turn into a hard jump.
        return [_frame(float(t), [_tr(1, 0.2 if t < 5 else 0.8)]) for t in range(10)]

    def test_mid_shot_boundary_pans_from_previous_x(self) -> None:
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

    def test_real_cut_reframes_hard(self) -> None:
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

    def _kinds(self, rungs: Any, **kw: Any) -> Any:
        plan = reconcile(
            [], [], cuts=[], src_w=SRC_W, src_h=SRC_H, duration=6.0, rungs=rungs, **kw
        )
        return sorted(p["kind"] for p in collect_escalation_points(plan))

    def test_no_subject_escalates_like_9x16(self) -> None:
        assert self._kinds(self.R34) == self._kinds(self.R916) == ["no_subject"]

    def test_wide_text_escalates_like_9x16(self) -> None:
        text_frames = [_txt(t, 0.9) for t in range(6)]
        assert (
            self._kinds(self.R34, text_frames=text_frames)
            == self._kinds(self.R916, text_frames=text_frames)
            == ["text_presence"]
        )

    def test_speaker_escalation_still_fires(self) -> None:
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
    def test_cuts_at_speaker_change(self) -> None:
        from reframe_plan import _speaker_turn_cuts

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 3.0},
            {"speaker_id": "B", "start_sec": 3.0, "end_sec": 6.0},
        ]
        assert _speaker_turn_cuts(segs, 1.8) == [3.0]

    def test_rapid_alternation_does_not_overfragment(self) -> None:
        from reframe_plan import _speaker_turn_cuts

        segs = [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 0.5},
            {"speaker_id": "B", "start_sec": 0.5, "end_sec": 1.0},
            {"speaker_id": "A", "start_sec": 1.0, "end_sec": 4.0},
        ]
        assert _speaker_turn_cuts(segs, 1.8) == []  # all turns within min dwell

    def test_empty(self) -> None:
        from reframe_plan import _speaker_turn_cuts

        assert _speaker_turn_cuts([], 1.8) == []
        assert _speaker_turn_cuts(None, 1.8) == []

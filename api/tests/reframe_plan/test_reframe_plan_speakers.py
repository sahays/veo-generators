"""Unit tests for the reframe v2 decision layer (rung selection + reconcile)."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_plan import (
    _segment_text_band,
    collect_escalation_points,
    pick_active_speaker,
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


class TestActiveSpeaker:
    TALK = [0.10, 0.45, 0.10, 0.50, 0.12]  # mouth oscillates → speaking
    STILL = [0.20, 0.21, 0.20, 0.19, 0.20]  # ~steady → listening

    def test_picks_clear_talker(self) -> None:
        assert pick_active_speaker({1: self.TALK, 2: self.STILL}) == 1

    def test_both_moving_is_ambiguous(self) -> None:
        assert pick_active_speaker({1: self.TALK, 2: self.TALK}) is None

    def test_silence_returns_none(self) -> None:
        assert pick_active_speaker({1: self.STILL, 2: self.STILL}) is None

    def test_too_few_samples_returns_none(self) -> None:
        assert pick_active_speaker({1: [0.1, 0.5]}) is None

    def test_equal_pair_keeps_both_despite_clear_talker(self) -> None:
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

    def test_reconcile_frames_speaker_when_listener_smaller(self) -> None:
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

    def test_reconcile_both_talking_keeps_both(self) -> None:
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


class TestSegmentTextBand:
    # _segment_text_band is the live measured-band accessor: median coverage + span
    # over the already-windowed text frames (reconcile bisect-slices per segment).
    def test_persistent_text_returns_median(self) -> None:
        win = [_txt(t, 0.8) for t in range(5)]
        cov, (x0, x1) = _segment_text_band(win)
        assert abs(cov - 0.8) < 1e-9
        assert x0 == 0.05 and abs(x1 - 0.85) < 1e-9

    def test_transient_flash_rejected(self) -> None:
        # One wide frame out of five → below the persistence floor → 0.
        win = [_txt(0, 0.9)] + [_txt(t, 0.0) for t in range(1, 5)]
        assert _segment_text_band(win) == (0.0, (0.0, 0.0))

    def test_empty_is_zero(self) -> None:
        assert _segment_text_band([]) == (0.0, (0.0, 0.0))


class TestReconcileWithText:
    # RETIRED floor: a wide measured text band never self-letterboxes. The CPU
    # can't tell a caption from a busy background, so it crops tight (fallback) and
    # ESCALATES the call to gemini-3.5-flash (Pass 2 applies any letterbox).
    def test_measured_wide_text_escalates(self) -> None:
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

    def test_dominant_face_with_wide_text_escalates(self) -> None:
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

    def test_no_wide_band_no_escalation(self) -> None:
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

    def test_requires_full_width_no_longer_refines(self) -> None:
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


class TestSplitLayout:
    # Two far-apart, static, persistent faces; neither mouth clearly dominates.
    def _frames(self, x1: Any = 0.25, x2: Any = 0.75, n: Any = 5) -> Any:
        return [_ftrm(t, [(1, x1, 0.2), (2, x2, 0.2)]) for t in range(n)]

    def _plan(self, frames: Any, scene: Any, duration: Any = 4.0) -> Any:
        return reconcile(
            [scene], frames, cuts=[], src_w=1920, src_h=1080, duration=duration
        )

    def test_static_far_apart_dialogue_splits(self) -> None:
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

    def test_side_by_side_layout_also_splits(self) -> None:
        plan = self._plan(self._frames(), _split_scene("general", "side_by_side"))
        assert plan[0]["layout"] == "split"

    def test_close_together_is_keep_both_not_split(self) -> None:
        # An equal close pair: one tight crop holds both (keep_both on the
        # tightest rung) — stacking would be pointless.
        plan = self._plan(self._frames(x1=0.45, x2=0.55), _split_scene())
        assert plan[0]["layout"] == "keep_both"
        assert plan[0]["inner_ar"] == (9, 16)  # span fits the full-bleed rung

    def test_moving_two_shot_keeps_both_not_split(self) -> None:
        # One subject drifts > SPLIT_MAX_MOTION → too busy to stack → keep_both.
        frames = [
            _ftrm(t, [(1, 0.25 + 0.04 * t, 0.2), (2, 0.75, 0.2)]) for t in range(5)
        ]
        seg = self._plan(frames, _split_scene())[0]
        assert seg["layout"] == "keep_both"

    def test_short_shot_does_not_split(self) -> None:
        # Below SPLIT_MIN_DWELL (3s) → stacking would read as a glitch → keep_both.
        plan = self._plan(self._frames(n=3), _split_scene(), duration=2.0)
        assert plan[0]["layout"] == "keep_both"

    def test_non_dialogue_does_not_split(self) -> None:
        # Wide separation but Gemini didn't call it dialogue/side_by_side.
        seg = self._plan(self._frames(), _split_scene("general"))[0]
        assert seg["layout"] == "keep_both"

    def test_dominant_speaker_on_equal_pair_still_frames_both(self) -> None:
        # PRODUCT RULE: a clear talker does not excuse losing an equally
        # prominent listener — the equal pair splits (gates pass here).
        talk = [0.10, 0.45, 0.10, 0.50, 0.12]
        frames = [_ftrm(t, [(1, 0.25, talk[t]), (2, 0.75, 0.2)]) for t in range(5)]
        seg = self._plan(frames, _split_scene())[0]
        assert seg["layout"] == "split"

    def test_dominant_speaker_follows_when_listener_smaller(self) -> None:
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

    def _frames(self, x1: Any = 0.25, x2: Any = 0.75, n: Any = 5) -> Any:
        # Far-apart, static, persistent; neither mouth clearly dominates.
        return [_ftrm(t, [(1, x1, 0.2), (2, x2, 0.2)]) for t in range(n)]

    def _two_speakers(self) -> Any:
        return [
            {"speaker_id": "A", "start_sec": 0.0, "end_sec": 2.0},
            {"speaker_id": "B", "start_sec": 2.0, "end_sec": 4.0},
        ]

    def test_diarization_dialogue_keeps_equal_pair_together(self) -> None:
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

    def test_diarization_dialogue_unequal_pair_escalates_speaker(self) -> None:
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

    def test_single_speaker_does_not_split(self) -> None:
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

    def test_no_diarization_does_not_split(self) -> None:
        # No speaker_segments at all (e.g. silent video) → no dialogue intent.
        plan = reconcile(
            [], self._frames(), cuts=[], src_w=1920, src_h=1080, duration=4.0
        )
        assert plan[0]["layout"] != "split"

    def test_brief_second_speaker_is_not_dialogue(self) -> None:
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

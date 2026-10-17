"""Tests for Pass 2 verdict application (reframe_decide.apply_verdicts)."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_decide import apply_verdicts  # noqa: E402

SRC_W, SRC_H = 1920, 1080


def _esc_seg(
    key: str = "text:left:0.0-1.0@0.5",
    coverage: float = 0.9,
    inner_ar: tuple[int, int] = (9, 16),
) -> dict[str, Any]:
    return {
        "start": 0.0,
        "end": 6.0,
        "inner_ar": inner_ar,
        "layout": "single",
        "reason": "9:16 — face",
        "trace": {"source": "face", "coverage": 0.316, "chosen_ar": list(inner_ar)},
        "escalate": {
            "kind": "text_presence",
            "key": key,
            "question": "caption or background?",
            "facts": {"text_coverage": coverage, "side": "left"},
            "fallback": {"action": "crop"},
        },
    }


def _v(key: str, action: str, coverage: float = 0.0) -> dict[str, Any]:
    return {"key": key, "action": action, "coverage": coverage}


def _subject_seg(key: str = "subject:0.3,0.7", chosen_tid: int = 1) -> dict[str, Any]:
    return {
        "start": 0.0,
        "end": 6.0,
        "inner_ar": (9, 16),
        "layout": "single",
        "reason": "face seg",
        "crops": [{"track_id": chosen_tid, "x_target": 0.3, "source": "face"}],
        "trace": {"source": "face", "coverage": 0.316},
        "escalate": {
            "kind": "subject_choice",
            "key": key,
            "question": "which subject?",
            "facts": {
                "candidates": [
                    {"track_id": 1, "x": 0.3, "frac": 1.0, "pos": "left"},
                    {"track_id": 2, "x": 0.7, "frac": 0.9, "pos": "right"},
                ],
                "n_faces": 2,
            },
            "fallback": {"action": "follow", "subject": "left"},
        },
    }


class TestApplyVerdicts:
    def test_letterbox_widens_rung(self) -> None:
        segs = [_esc_seg(coverage=0.9)]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (16, 9)  # widened to keep the side text
        assert "letterbox" in segs[0]["reason"]
        assert segs[0]["trace"]["source"] == "gemini_text"

    def test_crop_keeps_fallback(self) -> None:
        segs = [_esc_seg()]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "crop")], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)  # unchanged — follow the speaker
        assert segs[0]["escalate"]["verdict"]["action"] == "crop"  # still recorded

    def test_missing_verdict_keeps_fallback(self) -> None:
        segs = [_esc_seg()]
        changed = apply_verdicts(segs, [], SRC_W, SRC_H, None)
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)
        assert "verdict" not in segs[0]["escalate"]

    def test_verdict_coverage_overrides_facts(self) -> None:
        # A narrow letterbox (0.55) should take a tighter rung than full 16:9.
        segs = [_esc_seg(coverage=0.99)]
        apply_verdicts(
            segs,
            [_v(segs[0]["escalate"]["key"], "letterbox", 0.55)],
            SRC_W,
            SRC_H,
            None,
        )
        assert segs[0]["inner_ar"] == (1, 1)  # 0.55 fits 1:1 (0.5625), not full 16:9

    def test_non_escalated_segments_untouched(self) -> None:
        plain = {"start": 0, "end": 2, "inner_ar": (9, 16), "layout": "single"}
        segs = [plain, _esc_seg()]
        apply_verdicts(
            segs, [_v(segs[1]["escalate"]["key"], "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert segs[0] == plain  # untouched

    def test_unknown_key_ignored(self) -> None:
        segs = [_esc_seg()]
        changed = apply_verdicts(
            segs, [_v("other", "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)

    def test_missing_coverage_falls_back_to_measured_band(self) -> None:
        # Model says letterbox but omits `coverage` → use the measured band
        # (facts.text_coverage), NOT a full-width 16:9 jump.
        segs = [_esc_seg(coverage=0.55)]
        changed = apply_verdicts(
            segs,
            [{"key": segs[0]["escalate"]["key"], "action": "letterbox"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (1, 1)  # 0.55 fits 1:1, not 16:9

    def test_letterbox_always_widens_at_least_one_rung(self) -> None:
        # A small stated coverage maps back to the current tight rung — the
        # verdict said letterbox, so it must widen SOMETHING, not silently no-op.
        segs = [_esc_seg(coverage=0.2)]
        changed = apply_verdicts(
            segs,
            [_v(segs[0]["escalate"]["key"], "letterbox", 0.3)],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (4, 5)  # one rung looser than 9:16

    def test_letterbox_on_loosest_rung_is_noop(self) -> None:
        segs = [_esc_seg(inner_ar=(16, 9))]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "letterbox", 1.0)], SRC_W, SRC_H, None
        )
        assert changed == 0 and segs[0]["inner_ar"] == (16, 9)

    def _band_seg(
        self,
        band: tuple[float, float],
        x_target: float = 0.5,
        coverage: float = 0.6,
        inner_ar: tuple[int, int] = (9, 16),
    ) -> dict[str, Any]:
        return {
            "start": 0.0,
            "end": 6.0,
            "inner_ar": inner_ar,
            "layout": "single",
            "reason": "9:16 — face",
            "crops": [{"track_id": 1, "x_target": x_target, "source": "face"}],
            "trace": {"source": "face", "coverage": 0.316, "chosen_ar": list(inner_ar)},
            "escalate": {
                "kind": "text_presence",
                "key": f"text:both:{band[0]}-{band[1]}@{x_target}",
                "question": "caption?",
                "facts": {
                    "text_coverage": coverage,
                    "band": list(band),
                    "check_side": "both",
                },
                "fallback": {"action": "crop"},
            },
        }

    def test_offcenter_band_widens_to_contain_it(self) -> None:
        # Band (0.35, 0.95) around a subject at x=0.5: sizing the rung to the band
        # WIDTH (0.60 → 1:1) still clips the far edge, because the crop centers on
        # the subject, not the band. The widen must reach the band's farther edge
        # from the crop center (0.9 → full 16:9).
        seg = self._band_seg((0.35, 0.95), x_target=0.5, coverage=0.6)
        changed = apply_verdicts(
            [seg],
            [_v(seg["escalate"]["key"], "letterbox", 0.6)],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert seg["inner_ar"] == (16, 9)  # contains the off-center band, not (1, 1)

    def test_centered_band_not_overwidened(self) -> None:
        # A band symmetric about the subject needs only its width — containment must
        # not inflate it (no over-letterboxing regression). (0.30, 0.70) at x=0.5 →
        # req 0.40, so the stated 0.55 still lands on 1:1 as before.
        seg = self._band_seg((0.30, 0.70), x_target=0.5, coverage=0.55)
        apply_verdicts(
            [seg],
            [_v(seg["escalate"]["key"], "letterbox", 0.55)],
            SRC_W,
            SRC_H,
            None,
        )
        assert seg["inner_ar"] == (1, 1)  # unchanged from width-based sizing

    def test_letterbox_converts_split_to_single(self) -> None:
        # Stacked panels can't show a full-width caption — a letterbox verdict
        # over a split shot falls back to one wide centered crop.
        seg = _esc_seg(coverage=0.9)
        seg["layout"] = "split"
        seg["inner_ar"] = None
        seg["crops"] = [
            {"track_id": 1, "x_target": 0.25, "source": "split_top"},
            {"track_id": 2, "x_target": 0.75, "source": "split_bottom"},
        ]
        segs = [seg]
        changed = apply_verdicts(
            segs, [_v(seg["escalate"]["key"], "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert changed == 1
        assert seg["layout"] == "single" and seg["inner_ar"] == (16, 9)
        assert len(seg["crops"]) == 1 and seg["crops"][0]["source"] == "center"


class TestSubjectVerdicts:
    def test_follow_right_retargets_crop(self) -> None:
        segs = [_subject_seg()]
        changed = apply_verdicts(
            segs,
            [
                {
                    "key": segs[0]["escalate"]["key"],
                    "action": "follow",
                    "subject": "right",
                }
            ],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        crop = segs[0]["crops"][0]
        assert crop["track_id"] == 2 and crop["x_target"] == 0.7  # switched to right
        assert "right subject" in segs[0]["reason"]

    def test_follow_matching_fallback_no_change(self) -> None:
        # Verdict picks the same person already chosen (left) → no retarget.
        segs = [_subject_seg(chosen_tid=1)]
        changed = apply_verdicts(
            segs,
            [
                {
                    "key": segs[0]["escalate"]["key"],
                    "action": "follow",
                    "subject": "left",
                }
            ],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 0
        assert segs[0]["crops"][0]["track_id"] == 1

    def test_missing_subject_verdict_keeps_fallback(self) -> None:
        segs = [_subject_seg()]
        changed = apply_verdicts(segs, [], SRC_W, SRC_H, None)
        assert changed == 0
        assert segs[0]["crops"][0]["track_id"] == 1


class TestNoSubjectVerdicts:
    def _seg(self) -> dict[str, Any]:
        return {
            "start": 0.0,
            "end": 6.0,
            "inner_ar": (9, 16),
            "layout": "single",
            "reason": "no detection",
            "crops": [{"track_id": None, "x_target": 0.5}],
            "trace": {"source": "center", "coverage": 0.316},
            "escalate": {
                "kind": "no_subject",
                "key": "nosubj:0.0",
                "question": "graphic or scenery?",
                "facts": {"subject": "none", "crop_keeps": [0.34, 0.66]},
                "fallback": {"action": "crop"},
            },
        }

    def test_letterbox_widens_full_frame_graphic(self) -> None:
        segs = [self._seg()]
        changed = apply_verdicts(
            segs,
            [{"key": "nosubj:0.0", "action": "letterbox", "coverage": 1.0}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (16, 9)
        assert "full-frame graphic" in segs[0]["reason"]

    def test_crop_keeps_center_for_scenery(self) -> None:
        segs = [self._seg()]
        changed = apply_verdicts(
            segs, [{"key": "nosubj:0.0", "action": "crop"}], SRC_W, SRC_H, None
        )
        assert changed == 0 and segs[0]["inner_ar"] == (9, 16)


class TestWeakSubjectVerdicts:
    """#7b: a sole low-confidence face Gemini judges as graphic vs real person."""

    def _seg(self) -> dict[str, Any]:
        return {
            "start": 0.0,
            "end": 1.5,
            "inner_ar": (9, 16),
            "layout": "single",
            "reason": "9:16 (0.32) — face w=0.31",
            "crops": [{"track_id": 1, "x_target": 0.48, "source": "face"}],
            "trace": {"source": "face", "coverage": 0.316},
            "escalate": {
                "kind": "weak_subject",
                "key": "graphic:0.0",
                "question": "logo/title card or real person?",
                "facts": {
                    "subject_x": 0.48,
                    "crop_keeps": [0.32, 0.64],
                    "face_conf": 0.35,
                },
                "fallback": {"action": "crop"},
            },
        }

    def test_letterbox_widens_for_graphic(self) -> None:
        segs = [self._seg()]
        changed = apply_verdicts(
            segs,
            [{"key": "graphic:0.0", "action": "letterbox", "coverage": 1.0}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (16, 9)
        assert "full-frame graphic" in segs[0]["reason"]
        assert segs[0]["trace"]["source"] == "gemini_graphic"

    def test_crop_keeps_face_for_real_person(self) -> None:
        segs = [self._seg()]
        changed = apply_verdicts(
            segs, [{"key": "graphic:0.0", "action": "crop"}], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)
        assert segs[0]["crops"][0]["source"] == "face"

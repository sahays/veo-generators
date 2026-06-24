"""Tests for Pass 2 verdict application (reframe_decide.apply_verdicts)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_decide import apply_verdicts, build_cluster_block  # noqa: E402

SRC_W, SRC_H = 1920, 1080


def _esc_seg(key="text:left:0.0-1.0@0.5", coverage=0.9, inner_ar=(9, 16)):
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


def _v(key, action, coverage=0.0):
    return {"key": key, "action": action, "coverage": coverage}


class TestApplyVerdicts:
    def test_letterbox_widens_rung(self):
        segs = [_esc_seg(coverage=0.9)]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (16, 9)  # widened to keep the side text
        assert "letterbox" in segs[0]["reason"]
        assert segs[0]["trace"]["source"] == "gemini_text"

    def test_crop_keeps_fallback(self):
        segs = [_esc_seg()]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "crop")], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)  # unchanged — follow the speaker
        assert segs[0]["escalate"]["verdict"]["action"] == "crop"  # still recorded

    def test_missing_verdict_keeps_fallback(self):
        segs = [_esc_seg()]
        changed = apply_verdicts(segs, [], SRC_W, SRC_H, None)
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)
        assert "verdict" not in segs[0]["escalate"]

    def test_verdict_coverage_overrides_facts(self):
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

    def test_non_escalated_segments_untouched(self):
        plain = {"start": 0, "end": 2, "inner_ar": (9, 16), "layout": "single"}
        segs = [plain, _esc_seg()]
        apply_verdicts(
            segs, [_v(segs[1]["escalate"]["key"], "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert segs[0] == plain  # untouched

    def test_unknown_key_ignored(self):
        segs = [_esc_seg()]
        changed = apply_verdicts(
            segs, [_v("other", "letterbox", 0.9)], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)


def _subject_seg(key="subject:0.3,0.7", chosen_tid=1):
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


class TestSubjectVerdicts:
    def test_follow_right_retargets_crop(self):
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

    def test_follow_matching_fallback_no_change(self):
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

    def test_missing_subject_verdict_keeps_fallback(self):
        segs = [_subject_seg()]
        changed = apply_verdicts(segs, [], SRC_W, SRC_H, None)
        assert changed == 0
        assert segs[0]["crops"][0]["track_id"] == 1


class TestNoSubjectVerdicts:
    def _seg(self):
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

    def test_letterbox_widens_full_frame_graphic(self):
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

    def test_crop_keeps_center_for_scenery(self):
        segs = [self._seg()]
        changed = apply_verdicts(
            segs, [{"key": "nosubj:0.0", "action": "crop"}], SRC_W, SRC_H, None
        )
        assert changed == 0 and segs[0]["inner_ar"] == (9, 16)


class TestPrompt:
    def test_cluster_block_echoes_key(self):
        c = {
            "key": "text:left:0.0-1.0@0.5",
            "question": "caption?",
            "facts": {"side": "left"},
            "thumb_secs": [3.0],
        }
        block = build_cluster_block(c)
        assert "text:left:0.0-1.0@0.5" in block and "caption?" in block

"""Tests for Pass 2 verdict application (reframe_decide.apply_verdicts)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_decide import (  # noqa: E402
    _cluster_sample_secs,
    apply_verdicts,
    build_cluster_block,
    harmonize_letterbox,
)

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

    def test_missing_coverage_falls_back_to_measured_band(self):
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

    def test_letterbox_always_widens_at_least_one_rung(self):
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

    def test_letterbox_on_loosest_rung_is_noop(self):
        segs = [_esc_seg(inner_ar=(16, 9))]
        changed = apply_verdicts(
            segs, [_v(segs[0]["escalate"]["key"], "letterbox", 1.0)], SRC_W, SRC_H, None
        )
        assert changed == 0 and segs[0]["inner_ar"] == (16, 9)

    def test_letterbox_converts_split_to_single(self):
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


class TestWeakSubjectVerdicts:
    """#7b: a sole low-confidence face Gemini judges as graphic vs real person."""

    def _seg(self):
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

    def test_letterbox_widens_for_graphic(self):
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

    def test_crop_keeps_face_for_real_person(self):
        segs = [self._seg()]
        changed = apply_verdicts(
            segs, [{"key": "graphic:0.0", "action": "crop"}], SRC_W, SRC_H, None
        )
        assert changed == 0
        assert segs[0]["inner_ar"] == (9, 16)
        assert segs[0]["crops"][0]["source"] == "face"


class TestActiveSpeakerVerdicts:
    """#4: Gemini picks who is speaking; the crop re-centers on them (source=speaker)."""

    def _seg(self, chosen_tid=1):
        return {
            "start": 0.0,
            "end": 4.0,
            "inner_ar": (9, 16),
            "layout": "single",
            "reason": "9:16 — face",
            "crops": [{"track_id": chosen_tid, "x_target": 0.3, "source": "face"}],
            "trace": {"source": "face", "coverage": 0.316},
            "escalate": {
                "kind": "active_speaker",
                "key": "speaker:A:0.3,0.7",
                "question": "who is speaking?",
                "facts": {
                    "candidates": [
                        {"track_id": 1, "x": 0.3, "frac": 1.0, "pos": "left"},
                        {"track_id": 2, "x": 0.7, "frac": 1.0, "pos": "right"},
                    ],
                    "n_faces": 2,
                },
                "fallback": {"action": "follow", "subject": "left"},
            },
        }

    def test_center_right_speaker_retargets(self):
        segs = [self._seg(chosen_tid=1)]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.3,0.7", "action": "follow", "subject": "right"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        crop = segs[0]["crops"][0]
        assert crop["track_id"] == 2 and crop["source"] == "speaker"
        assert "center right speaker" in segs[0]["reason"]
        assert segs[0]["trace"]["source"] == "gemini_speaker"

    def test_confirming_fallback_no_change(self):
        # Gemini agrees with the fallback (left) → already centered, no retarget.
        segs = [self._seg(chosen_tid=1)]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.3,0.7", "action": "follow", "subject": "left"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 0 and segs[0]["crops"][0]["track_id"] == 1

    def test_letterbox_keeps_static_poster_wide(self):
        # No on-screen talker (poster / key art with VO) → Gemini answers letterbox →
        # keep it full width instead of cropping to a non-speaking face.
        segs = [self._seg(chosen_tid=1)]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.3,0.7", "action": "letterbox", "coverage": 1.0}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1 and segs[0]["inner_ar"] == (16, 9)
        assert "full-frame graphic" in segs[0]["reason"]


def _speaker_pair_seg(can_split=False):
    """An active_speaker escalation that OFFERED keep_both (and maybe split)."""
    facts = {
        "candidates": [
            {"track_id": 1, "x": 0.25, "w": 0.1, "frac": 1.0, "pos": "left"},
            {"track_id": 2, "x": 0.75, "w": 0.1, "frac": 1.0, "pos": "right"},
        ],
        "n_faces": 2,
        "pair": [1, 2],
        "can_keep_both": True,
    }
    if can_split:
        facts["can_split"] = True
    return {
        "start": 0.0,
        "end": 4.0,
        "inner_ar": (9, 16),
        "layout": "single",
        "reason": "9:16 — face",
        "crops": [{"track_id": 1, "x_target": 0.25, "source": "face"}],
        "trace": {"source": "face", "coverage": 0.316, "n_faces": 2},
        "escalate": {
            "kind": "active_speaker",
            "key": "speaker:A:0.2,0.8",
            "question": "who is speaking? (keep_both offered)",
            "facts": facts,
            "fallback": {"action": "follow", "subject": "left"},
        },
    }


class TestKeepBothSplitVerdicts:
    """#4 keep_both/split answers — a real two-shot conversation is framed as
    both people, not forced to one centered speaker or a letterbox."""

    def test_keep_both_frames_the_pair(self):
        segs = [_speaker_pair_seg()]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.2,0.8", "action": "keep_both"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        seg = segs[0]
        assert seg["layout"] == "keep_both"
        # span 0.2..0.8 (+face halves +margin) needs the full-width rung
        assert seg["inner_ar"] == (16, 9)
        assert len(seg["crops"]) == 1
        assert seg["crops"][0]["source"] == "center"
        assert abs(seg["crops"][0]["x_target"] - 0.5) < 1e-6
        assert seg["trace"]["source"] == "gemini_keep_both"

    def test_split_stacks_the_pair_when_offered(self):
        segs = [_speaker_pair_seg(can_split=True)]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.2,0.8", "action": "split"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        seg = segs[0]
        assert seg["layout"] == "split" and seg["inner_ar"] is None
        top, bot = seg["crops"]
        assert top["track_id"] == 1 and top["source"] == "split_top"
        assert bot["track_id"] == 2 and bot["source"] == "split_bottom"

    def test_speaker_letterbox_uses_carried_text_band(self):
        # The speaker question carried a text-band note (see _text_note); a
        # letterbox answer without coverage widens to the measured band, not
        # to full 16:9.
        segs = [_speaker_pair_seg()]
        segs[0]["escalate"]["facts"]["text_coverage"] = 0.55
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.2,0.8", "action": "letterbox"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (1, 1)

    def test_subject_choice_letterbox_widens(self):
        # subject_choice can also carry a text-band note → honor letterbox.
        segs = [_subject_seg()]
        segs[0]["escalate"]["facts"]["text_coverage"] = 0.9
        changed = apply_verdicts(
            segs,
            [{"key": segs[0]["escalate"]["key"], "action": "letterbox"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["inner_ar"] == (16, 9)

    def test_split_without_offer_degrades_to_keep_both(self):
        # The split gates didn't pass (planner never offered it) → the safe
        # reading of a split answer is keep-both in one wide crop.
        segs = [_speaker_pair_seg(can_split=False)]
        changed = apply_verdicts(
            segs,
            [{"key": "speaker:A:0.2,0.8", "action": "split"}],
            SRC_W,
            SRC_H,
            None,
        )
        assert changed == 1
        assert segs[0]["layout"] == "keep_both"


def _shot_seg(start, end, source, inner_ar, text=0.4, nf=1, at_cut=False):
    return {
        "start": start,
        "end": end,
        "inner_ar": inner_ar,
        "layout": "single",
        "reason": "r",
        "crops": [{"track_id": 1, "x_target": 0.5, "source": "face"}],
        "trace": {"source": source, "text_measured": text, "n_faces": nf},
        "starts_at_cut": at_cut,
    }


class TestHarmonizeLetterbox:
    """A text letterbox that covers part of a shot is extended to same-shot
    neighbors that also measured text — no bars popping mid-shot."""

    def test_extends_forward_within_shot(self):
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16)),  # band dipped; same shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 1
        assert segs[1]["inner_ar"] == (16, 9)
        assert segs[1]["trace"]["source"] == "gemini_text"

    def test_stops_at_real_cut(self):
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), at_cut=True),  # new shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16)

    def test_stops_at_textless_cell(self):
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), text=0.0),  # no text here
            _shot_seg(10, 15, "face", (9, 16)),  # ...so this is not reached
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16) and segs[2]["inner_ar"] == (9, 16)

    def test_extends_backward_and_respects_faceness(self):
        segs = [
            _shot_seg(0, 5, "face", (9, 16), nf=0, at_cut=True),  # graphic cell
            _shot_seg(5, 10, "gemini_text", (16, 9), nf=1),
        ]
        # face/no-face state differs → not extended backward
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[0]["inner_ar"] == (9, 16)

    def test_bridges_a_band_dip_between_letterboxed_cells(self):
        # The middle cell's band dipped below the persistence floor (measures
        # 0.0) but the same caption is letterboxed on both sides — bridging it
        # stops the bars flickering out and back mid-caption.
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), text=0.0),  # the dip
            _shot_seg(10, 15, "gemini_text", (16, 9)),
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 1
        assert segs[1]["inner_ar"] == (16, 9)

    def test_dip_before_a_real_cut_not_bridged(self):
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), text=0.0),
            _shot_seg(10, 15, "gemini_text", (16, 9), at_cut=True),  # new shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16)


class TestClusterSampleSecs:
    def test_multi_segment_cluster_uses_thumb_secs_not_span(self):
        # A caption recurs at 0:05 and 3:20; the cluster span covers the gap.
        # Sampling fractions of [5, 200] would land at ~44s/102s/161s — moments
        # the caption isn't on screen. We must sample the real segment midpoints.
        cluster = {"start": 5.0, "end": 200.0, "thumb_secs": [8.0, 203.0]}
        secs = _cluster_sample_secs(cluster)
        assert secs == [8.0, 203.0]

    def test_single_segment_cluster_keeps_intra_shot_spread(self):
        # One contiguous shot → 3 frames across it (more coverage than 1 midpoint).
        cluster = {"start": 0.0, "end": 10.0, "thumb_secs": [5.0]}
        secs = _cluster_sample_secs(cluster)
        assert secs == [2.0, 5.0, 8.0]

    def test_thumb_secs_capped(self):
        cluster = {"start": 0.0, "end": 9.0, "thumb_secs": [1.0, 4.0, 7.0, 8.5]}
        assert len(_cluster_sample_secs(cluster)) == 3

    def test_missing_thumb_secs_falls_back_to_span(self):
        cluster = {"start": 0.0, "end": 10.0}
        assert _cluster_sample_secs(cluster) == [2.0, 5.0, 8.0]

    def test_zero_length_cluster_without_thumbs_returns_start(self):
        cluster = {"start": 4.0, "end": 4.0}
        assert _cluster_sample_secs(cluster) == [4.0]


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

"""Tests for Pass 2 speaker verdicts, letterbox harmonization, and cluster sampling."""

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reframe_decide import (  # noqa: E402
    _cluster_sample_secs,
    apply_verdicts,
    build_cluster_block,
    harmonize_letterbox,
)

SRC_W, SRC_H = 1920, 1080


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


def _speaker_pair_seg(can_split: bool = False) -> dict[str, Any]:
    """An active_speaker escalation that OFFERED keep_both (and maybe split)."""
    facts: dict[str, Any] = {
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


def _shot_seg(
    start: float,
    end: float,
    source: str,
    inner_ar: tuple[int, int],
    text: float = 0.4,
    nf: int = 1,
    at_cut: bool = False,
) -> dict[str, Any]:
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


class TestActiveSpeakerVerdicts:
    """#4: Gemini picks who is speaking; the crop re-centers on them (source=speaker)."""

    def _seg(self, chosen_tid: int = 1) -> dict[str, Any]:
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

    def test_center_right_speaker_retargets(self) -> None:
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

    def test_confirming_fallback_no_change(self) -> None:
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

    def test_letterbox_keeps_static_poster_wide(self) -> None:
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


class TestKeepBothSplitVerdicts:
    """#4 keep_both/split answers — a real two-shot conversation is framed as
    both people, not forced to one centered speaker or a letterbox."""

    def test_keep_both_frames_the_pair(self) -> None:
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

    def test_split_stacks_the_pair_when_offered(self) -> None:
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

    def test_speaker_letterbox_uses_carried_text_band(self) -> None:
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

    def test_subject_choice_letterbox_widens(self) -> None:
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

    def test_split_without_offer_degrades_to_keep_both(self) -> None:
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


class TestHarmonizeLetterbox:
    """A text letterbox that covers part of a shot is extended to same-shot
    neighbors that also measured text — no bars popping mid-shot."""

    def test_extends_forward_within_shot(self) -> None:
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16)),  # band dipped; same shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 1
        assert segs[1]["inner_ar"] == (16, 9)
        assert segs[1]["trace"]["source"] == "gemini_text"

    def test_stops_at_real_cut(self) -> None:
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), at_cut=True),  # new shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16)

    def test_stops_at_textless_cell(self) -> None:
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), text=0.0),  # no text here
            _shot_seg(10, 15, "face", (9, 16)),  # ...so this is not reached
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16) and segs[2]["inner_ar"] == (9, 16)

    def test_extends_backward_and_respects_faceness(self) -> None:
        segs = [
            _shot_seg(0, 5, "face", (9, 16), nf=0, at_cut=True),  # graphic cell
            _shot_seg(5, 10, "gemini_text", (16, 9), nf=1),
        ]
        # face/no-face state differs → not extended backward
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[0]["inner_ar"] == (9, 16)

    def test_bridges_a_band_dip_between_letterboxed_cells(self) -> None:
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

    def test_dip_before_a_real_cut_not_bridged(self) -> None:
        segs = [
            _shot_seg(0, 5, "gemini_text", (16, 9), at_cut=True),
            _shot_seg(5, 10, "face", (9, 16), text=0.0),
            _shot_seg(10, 15, "gemini_text", (16, 9), at_cut=True),  # new shot
        ]
        assert harmonize_letterbox(segs, SRC_W, SRC_H) == 0
        assert segs[1]["inner_ar"] == (9, 16)


class TestClusterSampleSecs:
    def test_multi_segment_cluster_uses_thumb_secs_not_span(self) -> None:
        # A caption recurs at 0:05 and 3:20; the cluster span covers the gap.
        # Sampling fractions of [5, 200] would land at ~44s/102s/161s — moments
        # the caption isn't on screen. We must sample the real segment midpoints.
        cluster = {"start": 5.0, "end": 200.0, "thumb_secs": [8.0, 203.0]}
        secs = _cluster_sample_secs(cluster)
        assert secs == [8.0, 203.0]

    def test_single_segment_cluster_keeps_intra_shot_spread(self) -> None:
        # One contiguous shot → 3 frames across it (more coverage than 1 midpoint).
        cluster = {"start": 0.0, "end": 10.0, "thumb_secs": [5.0]}
        secs = _cluster_sample_secs(cluster)
        assert secs == [2.0, 5.0, 8.0]

    def test_thumb_secs_capped(self) -> None:
        cluster = {"start": 0.0, "end": 9.0, "thumb_secs": [1.0, 4.0, 7.0, 8.5]}
        assert len(_cluster_sample_secs(cluster)) == 3

    def test_missing_thumb_secs_falls_back_to_span(self) -> None:
        cluster = {"start": 0.0, "end": 10.0}
        assert _cluster_sample_secs(cluster) == [2.0, 5.0, 8.0]

    def test_zero_length_cluster_without_thumbs_returns_start(self) -> None:
        cluster = {"start": 4.0, "end": 4.0}
        assert _cluster_sample_secs(cluster) == [4.0]


class TestPrompt:
    def test_cluster_block_echoes_key(self) -> None:
        c = {
            "key": "text:left:0.0-1.0@0.5",
            "question": "caption?",
            "facts": {"side": "left"},
            "thumb_secs": [3.0],
        }
        block = build_cluster_block(c)
        assert "text:left:0.0-1.0@0.5" in block and "caption?" in block

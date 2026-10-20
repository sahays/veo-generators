"""Script adherence: Hindi transcript matching, language, extra speech, order, missing lines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval_clips import FFMPEG, SPEC, moving_clip

from storygraph.adapters.mock import MockVLMProvider
from storygraph.adapters.transcribe import Transcript, TranscriptSegment
from storygraph.config import Config
from storygraph.eval.contracts import EvalInput
from storygraph.eval.engine import EvalEngine
from storygraph.eval.metrics.bundle import scripted_lines
from storygraph.eval.metrics.dialogue import match_dialogue
from storygraph.qa.critic.checks import CriticThresholds

LINES = scripted_lines(SPEC)


def _seg(
    t: float, text: str, lang: str = "", speaker: str = "Pip"
) -> TranscriptSegment:
    return TranscriptSegment(
        t_start=t, t_end=t + 1.0, text=text, lang=lang, speaker=speaker
    )


def test_hindi_lines_match_despite_punctuation_and_spacing() -> None:
    heard = Transcript(segments=[_seg(0.5, "नमस्ते  मिलो"), _seg(2.0, "चलो, खेलते हैं")])
    match = match_dialogue(LINES, heard)
    assert [m.similarity for m in match.lines] == [1.0, 1.0]
    assert all(m.lang_ok and m.in_order and m.speaker_ok for m in match.lines)
    assert match.extra == [] and match.order_ok


def test_romanized_speech_is_wrong_language_and_text() -> None:
    match = match_dialogue(LINES, Transcript(segments=[_seg(0.5, "namaste milo")]))
    assert all(
        m.segment is None for m in match.lines
    )  # Latin never aligns to Devanagari
    assert [s.text for s in match.extra] == ["namaste milo"]
    tagged = match_dialogue(
        LINES, Transcript(segments=[_seg(0.5, "नमस्ते मिलो", lang="en")])
    )
    assert tagged.lines[0].lang_ok is False


def test_extra_and_out_of_order_speech() -> None:
    heard = Transcript(
        segments=[_seg(0.2, "चलो खेलते हैं"), _seg(1.5, "नमस्ते मिलो"), _seg(3.0, "यह कौन है")]
    )
    match = match_dialogue(LINES, heard)
    assert not match.order_ok
    assert [m.in_order for m in match.lines].count(False) == 1
    assert all(m.segment is not None for m in match.lines)
    assert [s.text for s in match.extra] == ["यह कौन है"]


class _FixedTranscriber:
    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript

    def transcribe(
        self, clip_bytes: bytes, speakers: list[str], langs: list[str]
    ) -> Transcript:
        return self.transcript


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg")
def test_script_dimension_defects_and_hard_gate(
    tmp_path: Path, default_cfg: Config
) -> None:
    heard = Transcript(segments=[_seg(0.5, "नमस्ते मिलो"), _seg(2.5, "मुझे भूख लगी है")])
    engine = EvalEngine(
        vlm=MockVLMProvider(),
        gate_cfg=default_cfg.eval,
        thr=CriticThresholds.from_cfg(default_cfg.qa),
        transcriber=_FixedTranscriber(heard),
        run_cv=False,
    )
    clip = moving_clip(tmp_path / "talk.mp4", 4.0).read_bytes()
    res = engine.evaluate(EvalInput(clip_bytes=clip, spec_json=json.dumps(SPEC)))
    script = res.results["script_adherence"]
    kinds = {(d.type, d.severity) for d in script.defects}
    assert kinds == {("line_missing", "high"), ("unscripted_speech", "medium")}
    assert script.sub_scores["dialogue_wer"] == 0.5 and script.confidence == 0.8
    assert any(e.t_s == 2.5 for e in script.evidence)

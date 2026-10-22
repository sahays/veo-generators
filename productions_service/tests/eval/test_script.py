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
from storygraph.eval.dimensions.script_dialogue import _dialogue_from_transcript
from storygraph.eval.engine import EvalEngine
from storygraph.eval.metrics.bundle import scripted_lines
from storygraph.eval.metrics.dialogue import ScriptedLine, match_dialogue
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


def _span(t0: float, t1: float, text: str, speaker: str = "Pip") -> TranscriptSegment:
    return TranscriptSegment(t_start=t0, t_end=t1, text=text, speaker=speaker)


CORD = ScriptedLine(
    "Pip", "en-IN", "The binding cord is freed; now surrender your quiet cargo."
)
SPHERE = ScriptedLine(
    "Pip", "en-IN", "Behold the crimson sphere, freed from wooden shadows."
)


def _kinds(
    lines: list[ScriptedLine], segs: list[TranscriptSegment]
) -> set[tuple[str, str]]:
    defects, _ = _dialogue_from_transcript(
        match_dialogue(lines, Transcript(segments=segs)), 8.0
    )
    return {(d.type, d.severity) for d in defects}


def test_transcriber_split_lines_merge_into_one_match() -> None:
    """p-0irbygdv: Omni spoke both lines verbatim; the transcriber split each in two."""
    segs = [
        _span(1.05, 2.40, "The binding cord is freed."),
        _span(3.25, 4.60, "Now surrender your quiet cargo."),
        _span(5.20, 6.00, "Behold the crimson sphere,", speaker=""),
        _span(6.24, 7.50, "freed from wooden shadows."),
    ]
    match = match_dialogue([CORD, SPHERE], Transcript(segments=segs))
    assert [m.span for m in match.lines] == [(0, 2), (2, 4)]
    assert all(m.similarity >= 0.95 and m.in_order for m in match.lines)
    assert match.extra == [] and match.order_ok
    assert _kinds([CORD, SPHERE], segs) == set()


def test_partial_line_is_medium_render_defect() -> None:
    segs = [_span(3.25, 4.60, "Now surrender your quiet cargo.")]
    defects, _ = _dialogue_from_transcript(
        match_dialogue([CORD], Transcript(segments=segs)), 8.0
    )
    assert [(d.type, d.severity, d.likely_cause) for d in defects] == [
        ("line_partial", "medium", "render")
    ]


def test_genuinely_different_line_is_high_and_unscripted() -> None:
    segs = [_span(1.0, 3.0, "Where did my little brass key go this morning?")]
    assert _kinds([CORD], segs) == {
        ("line_missing", "high"),
        ("unscripted_speech", "medium"),
    }


def test_split_merge_respects_gap_and_speaker_and_keeps_real_extras() -> None:
    far = [
        _span(0.0, 1.0, "The binding cord is freed."),
        _span(3.0, 4.0, "Now surrender your quiet cargo."),
    ]
    assert match_dialogue([CORD], Transcript(segments=far)).lines[0].span != (0, 2)
    other = [far[0], _span(1.5, 2.5, "Now surrender your quiet cargo.", speaker="Ava")]
    assert match_dialogue([CORD], Transcript(segments=other)).lines[0].span != (0, 2)
    segs = [
        _span(1.05, 2.40, "The binding cord is freed."),
        _span(3.25, 4.60, "Now surrender your quiet cargo."),
        _span(4.00, 4.40, "uh huh", speaker=""),
        _span(6.50, 8.00, "I will hide the key under the stool."),
    ]
    match = match_dialogue([CORD], Transcript(segments=segs))
    assert match.lines[0].span == (0, 2)
    assert [s.text for s in match.extra] == ["I will hide the key under the stool."]


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

"""Line timing from transcripts and bounded time-fitting (never cut words)."""

from __future__ import annotations

import pytest
from storygraph.adapters.transcribe import Transcript, TranscriptSegment
from storygraph.audio.voice.separation import duck_filter
from storygraph.audio.voice.timefit import place_lines, plan_fit
from storygraph.audio.voice.timing import (
    LineSlot,
    SpeechLine,
    line_slots,
    speech_windows,
)

BOUNDS = (0.8, 1.25)


def _line(i: int, text: str, who: str = "Pip") -> SpeechLine:
    return SpeechLine(f"l{i}", f"char_{who.lower()}", who, "en", text)


def _seg(a: float, b: float, text: str, who: str = "Pip") -> TranscriptSegment:
    return TranscriptSegment(t_start=a, t_end=b, text=text, speaker=who, lang="en")


def test_split_transcript_segments_merge_into_one_slot_and_missing_line_is_estimated() -> (
    None
):
    lines = [
        _line(1, "The binding cord is freed; now surrender your quiet cargo."),
        _line(2, "Hold fast now."),
    ]
    t = Transcript(
        segments=[
            _seg(1.0, 2.4, "The binding cord is freed."),
            _seg(2.6, 4.2, "Now surrender your quiet cargo."),
        ]
    )
    slots = line_slots(lines, t, clip_s=8.0)
    assert (slots[0].start, slots[0].end, slots[0].estimated) == (1.0, 4.2, False)
    assert slots[1].estimated and slots[1].start >= 4.2
    assert slots[1].end <= 8.0


def test_tempo_is_clamped_and_long_lines_shift_earlier_instead_of_being_cut() -> None:
    fit = plan_fit(4.0, (3.0, 5.0), (1.0, 5.2), BOUNDS)  # needs 2.0x; capped at 1.25
    assert fit.tempo == 1.25
    assert fit.end - fit.start == pytest.approx(3.2)
    assert fit.end == pytest.approx(5.2) and fit.start == pytest.approx(2.0)
    assert fit.overrun_s == 0.0
    short = plan_fit(1.0, (3.0, 5.0), (0.0, 8.0), BOUNDS)
    assert short.tempo == 0.8 and short.start == 3.0  # onset anchored to lip movement


def test_overrun_is_reported_when_no_free_space_remains() -> None:
    fit = plan_fit(5.0, (0.0, 2.0), (0.0, 2.5), BOUNDS)
    assert fit.tempo == 1.25 and fit.overrun_s == pytest.approx(1.5)


def test_place_lines_keeps_lines_ordered_without_overlap() -> None:
    slots = [
        LineSlot(_line(1, "a b c"), 0.5, 2.0),
        LineSlot(_line(2, "d e f"), 2.2, 3.5),
    ]
    plans = place_lines(slots, [2.4, 1.0], clip_s=6.0, tempo_bounds=BOUNDS)
    assert plans[0].end <= plans[1].start
    assert plans[1].start == pytest.approx(2.2)


def test_speech_windows_merge_and_duck_gain() -> None:
    t = Transcript(
        segments=[_seg(1.0, 2.0, "x"), _seg(2.1, 3.0, "y"), _seg(5.0, 6.0, "z")]
    )
    assert speech_windows(t, [], [(6.2, 6.5)]) == [
        pytest.approx((0.85, 3.15)),
        pytest.approx((4.85, 6.65)),  # VAD activity merges with the last segment
    ]
    assert "1-0.87411*" in duck_filter([(1.0, 2.0)], -18.0)  # 10^(-18/20) = 0.12589
    assert duck_filter([], -18.0) == "anull"

"""Line timings for voiceover: scripted lines aligned to the clip transcript.

Matched lines take their merged transcript window (`match_dialogue` -> monotonic
`align_lines`). Lines Omni never said get an *estimated* slot after the previous line,
sized by a speaking-rate heuristic, so every scripted line is still voiced.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...adapters.transcribe import Transcript
from ...eval.metrics.dialogue import ScriptedLine, match_dialogue

EST_WORDS_PER_S = 2.6
EST_GAP_S = 0.25
EST_LEAD_IN_S = 0.4
MIN_SLOT_S = 0.4
WINDOW_PAD_S = 0.15

Window = tuple[float, float]


@dataclass(frozen=True)
class SpeechLine:
    """One scripted line to voice (typed contract between pipeline and sync)."""

    line_id: str
    speaker_id: str
    speaker_name: str
    lang: str
    text: str
    delivery: str = ""


@dataclass(frozen=True)
class LineSlot:
    line: SpeechLine
    start: float
    end: float
    estimated: bool = False


def _estimated(line: SpeechLine, after: float, clip_s: float) -> LineSlot:
    length = max(MIN_SLOT_S, len(line.text.split()) / EST_WORDS_PER_S)
    start = min(after, max(0.0, clip_s - length))
    return LineSlot(line, start, min(clip_s, start + length), estimated=True)


def line_slots(
    lines: list[SpeechLine], transcript: Transcript, clip_s: float
) -> list[LineSlot]:
    """One slot per scripted line, in script order (matched windows or estimates)."""
    scripted = [ScriptedLine(ln.speaker_name, ln.lang, ln.text) for ln in lines]
    matches = match_dialogue(scripted, transcript).lines
    slots: list[LineSlot] = []
    cursor = EST_LEAD_IN_S
    for line, match in zip(lines, matches, strict=True):
        seg = match.segment
        if seg is not None and seg.t_end > seg.t_start:
            slot = LineSlot(line, max(0.0, seg.t_start), min(clip_s, seg.t_end))
        else:
            slot = _estimated(line, cursor, clip_s)
        slots.append(slot)
        cursor = slot.end + EST_GAP_S
    return slots


def merge_windows(windows: list[Window], pad: float = WINDOW_PAD_S) -> list[Window]:
    """Padded, sorted, overlap-merged windows (O(n log n))."""
    merged: list[Window] = []
    for a, b in sorted((max(0.0, a - pad), b + pad) for a, b in windows if b > a):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def speech_windows(
    transcript: Transcript, slots: list[LineSlot], voice: list[Window] | None = None
) -> list[Window]:
    """Where Omni may be speaking: transcript segments, line slots and VAD activity."""
    raw = [(s.t_start, s.t_end) for s in transcript.segments]
    raw += [(s.start, s.end) for s in slots if not s.estimated]
    raw += voice or []
    return merge_windows(raw)

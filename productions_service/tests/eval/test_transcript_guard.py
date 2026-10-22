"""Regression: an empty transcript must never turn into false 'line_missing' defects (p-0irbygdv)."""

from __future__ import annotations

from storygraph.adapters.audio_levels import AudioLevels
from storygraph.adapters.transcribe import (
    Transcript,
    TranscriptPayload,
    TranscriptSegment,
)
from storygraph.eval.metrics.bundle import _guard_empty_transcript
from storygraph.eval.metrics.dialogue import ScriptedLine

_LINE = [ScriptedLine(speaker="Ava", lang="en-IN", text="At last, the golden tooth.")]


def test_wire_schema_requires_segments() -> None:
    """Optional `segments` let gemini return {'available': true}; the wire schema must require it."""
    schema = TranscriptPayload.model_json_schema()
    assert "segments" in schema.get("required", [])
    assert "available" not in schema.get("properties", {})


def test_empty_transcript_on_audible_clip_is_unavailable() -> None:
    guarded = _guard_empty_transcript(
        Transcript(), _LINE, AudioLevels(-26.0, -4.0), "s1"
    )
    assert guarded.available is False


def test_empty_transcript_on_silent_clip_stays_available() -> None:
    guarded = _guard_empty_transcript(
        Transcript(), _LINE, AudioLevels(-91.0, -91.0), "s1"
    )
    assert guarded.available is True and guarded.segments == []


def test_non_empty_transcript_is_untouched() -> None:
    seg = TranscriptSegment(t_start=4.3, t_end=8.0, text="At last, the golden tooth.")
    guarded = _guard_empty_transcript(
        Transcript(segments=[seg]), _LINE, AudioLevels(-26.0, -4.0), "s1"
    )
    assert guarded.available is True and guarded.segments[0].t_start == 4.3

"""Typed data contracts for the voiceover-sync experiment (inputs, per-line and per-clip results)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ...audio.voice.timing import SpeechLine
from ...schemas.voice import VoicedLine


@dataclass(frozen=True)
class ClipCase:
    clip_id: str
    shot_id: str
    path: Path
    lines: list[SpeechLine]


class LineEval(BaseModel):
    line_id: str
    speaker_id: str
    text: str
    voiced_similarity: float = 0.0  # transcript of voiced clip vs scripted line
    heard_complete: bool = False
    onset_offset_s: float | None = None  # voiced onset - original Omni onset
    orig_f0_hz: float | None = None
    voiced_f0_hz: float | None = None


class ClipEval(BaseModel):
    clip_id: str
    remover: str
    voiced_path: str
    runtime_s: float
    lines: list[LineEval] = Field(default_factory=list)
    placements: list[VoicedLine] = Field(default_factory=list)
    bed_orig_db: float | None = None  # level outside speech windows (SFX/ambience)
    bed_voiced_db: float | None = None
    extra_speech: list[str] = Field(default_factory=list)  # unscripted words heard
    mix: MixJudgement | None = None


class VoiceJudgement(BaseModel):
    """Gemini audio judgement over one character's excerpts from several clips."""

    same_speaker_score: float = Field(
        description="0..1: 1 = all excerpts are one voice."
    )
    distinct_voices: int = Field(description="How many different voices are heard.")
    notes: str = Field(description="One or two sentences on timbre/pitch/age/gender.")


class MixJudgement(BaseModel):
    """Gemini listening judgement of one voiced clip's mix."""

    residual_voice: Literal["none", "faint", "clear"] = Field(
        description="Second quieter voice audible under/around the dialogue."
    )
    sfx_present: bool = Field(description="Non-speech SFX/ambience audible.")
    mix_naturalness: float = Field(description="0..1 natural dialogue-in-scene mix.")
    notes: str = Field(description="One sentence.")


class ExperimentReport(BaseModel):
    voices: dict[str, str] = Field(default_factory=dict)
    clips: list[ClipEval] = Field(default_factory=list)
    judgements: dict[str, VoiceJudgement] = Field(
        default_factory=dict
    )  # key: who|variant
    f0_spread_hz: dict[str, float] = Field(default_factory=dict)  # key: who|variant

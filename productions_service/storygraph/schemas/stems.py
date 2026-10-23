"""Layer 5 audio stems: per-run stem set and the typed stem-mix contract rendered in S10.

Omni's own audio is a *guide track* only (line timing); final audio = our stems.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .voice import VoicedLine

SfxSource = Literal["demucs", "graph", "hybrid"]


class StemSet(BaseModel):
    """Stems stored per GenerationRun so remixing never needs a re-render."""

    dialogue_uri: str  # fixed-voice TTS placed on the guide timings (WAV, clip length)
    sfx_uri: str  # SFX/ambience stem (WAV, clip length), no Omni voice
    sfx_source: SfxSource = "demucs"
    duration_s: float
    lines: list[VoicedLine] = Field(default_factory=list)
    pipeline_version: str = "stems-v1"


class StemMix(BaseModel):
    """One clip's mix: stem URIs + gains (dB) + loudness targets (LUFS).

    Music ducks under the dialogue stem only (sidechain keyed on dialogue, not SFX).
    """

    dialogue_uri: str
    sfx_uri: str
    music_uri: str | None = None
    dialogue_lufs: float = -16.0
    sfx_lufs: float = -24.0
    music_lufs: float = -26.0
    dialogue_gain_db: float = 0.0
    sfx_gain_db: float = 0.0
    music_gain_db: float = 0.0
    duck_threshold: float = Field(default=0.05, gt=0.0, le=1.0)
    duck_ratio: float = Field(default=8.0, ge=1.0, le=20.0)

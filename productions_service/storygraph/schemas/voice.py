"""Layer 1/5 voice models: a character's fixed TTS voice and a clip's voiceover record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VoiceArchetype = Literal[
    "robot",
    "child_female",
    "child_male",
    "adult_female",
    "adult_male",
    "elder_female",
    "elder_male",
    "creature",
    "neutral",
]
VoiceSelectedBy = Literal["auto", "human"]
SpeechRemoval = Literal["duck", "demucs"]


class VoiceProfile(BaseModel):
    """One speaking character's fixed voice, chosen once and reused for every line.

    `selected_by="human"` marks a manual edit; automatic selection never overwrites it.
    """

    provider: Literal["gemini-tts"] = "gemini-tts"
    model: str = "gemini-2.5-flash-tts"
    voice_name: str
    archetype: VoiceArchetype = "neutral"
    style_prompt: str = ""
    selected_by: VoiceSelectedBy = "auto"
    selector_version: str = "voice-registry-v1"


class VoicedLine(BaseModel):
    """How one scripted line was placed in the voiced clip (seconds, clip timeline)."""

    line_id: str
    speaker_id: str
    voice_name: str
    slot_start_s: float
    slot_end_s: float
    placed_start_s: float
    placed_end_s: float
    tempo: float = 1.0
    estimated_slot: bool = False  # True when the line was not found in the transcript
    overrun_s: float = 0.0  # speech past the slot that could not be absorbed


class VoiceoverRecord(BaseModel):
    """Append-only voiceover outcome recorded on a `GenerationRun` (original clip is kept)."""

    voiced_video_uri: str
    speech_removal: SpeechRemoval = "duck"
    tts_model: str = ""
    lines: list[VoicedLine] = Field(default_factory=list)
    pipeline_version: str = "voiceover-sync-v1"

"""Pydantic draft models and language maps for StoryGraph Role Agents."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...schema import (
    ActionBeat,
    CameraSpec,
    CastInShot,
    ClipScript,
    EntityType,
    InteractionStep,
    ShotLook,
    StateEffect,
)

LANGUAGE_PROMPT_NAMES: dict[str, str] = {
    "hi": "Hindi (Devanagari script, e.g. 'सीता, इस रेखा को पार मत करना।')",
    "hi-in": "Hindi (Devanagari script, e.g. 'सीता, इस रेखा को पार मत करना।')",
    "ta": "Tamil (Tamil script)",
    "ta-in": "Tamil (Tamil script)",
    "te": "Telugu (Telugu script)",
    "te-in": "Telugu (Telugu script)",
    "bn": "Bengali (Bengali script)",
    "bn-in": "Bengali (Bengali script)",
    "mr": "Marathi (Devanagari script)",
    "mr-in": "Marathi (Devanagari script)",
    "gu": "Gujarati (Gujarati script)",
    "gu-in": "Gujarati (Gujarati script)",
    "kn": "Kannada (Kannada script)",
    "kn-in": "Kannada (Kannada script)",
    "ml": "Malayalam (Malayalam script)",
    "ml-in": "Malayalam (Malayalam script)",
    "pa": "Punjabi (Gurmukhi script)",
    "pa-in": "Punjabi (Gurmukhi script)",
    "en": "English",
    "en-us": "English",
    "en-in": "English",
}


class SceneDraft(BaseModel):
    scene_id: str
    index: int
    heading: str
    location_id: str
    location_name: str
    time_of_day: str = "night"
    weather: str = "clear"
    summary: str
    mood: str = "cinematic"


class EventDraft(BaseModel):
    event_id: str
    story_order: int
    scene_id: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)


class StoryArchitectOutput(BaseModel):
    visual_medium: str = "Anamorphic 35mm live-action cinema"
    palette: list[str] = Field(
        default_factory=lambda: ["deep teal", "warm amber", "charcoal shadow"]
    )
    lens_language: str = "Panavision C-Series anamorphic primes, shallow depth of field"
    lighting_rules: str = (
        "Motivated practical tungsten key with cool atmospheric rim light"
    )
    aspect_ratio: str = "16:9"
    avoid: list[str] = Field(
        default_factory=lambda: [
            "text overlays",
            "watermarks",
            "cartoonish rendering",
            "deformed limbs",
        ]
    )
    scenes: list[SceneDraft] = Field(default_factory=list)
    events: list[EventDraft] = Field(default_factory=list)


class AttributeKV(BaseModel):
    key: str
    value: str


class ExtractedEntityDraft(BaseModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: list[AttributeKV] = Field(default_factory=list)


class ScriptSupervisorOutput(BaseModel):
    entities: list[ExtractedEntityDraft] = Field(default_factory=list)
    events: list[EventDraft] = Field(default_factory=list)


class DialogueLineDraft(BaseModel):
    line_id: str
    order_in_scene: int
    speaker_id: str
    addressee_id: str | None = None
    text: str
    delivery: str = "natural"
    language: str = "en"


class ScreenwriterOutput(BaseModel):
    summary: str
    mood: str
    interaction_steps: list[InteractionStep] = Field(default_factory=list)
    dialogue_lines: list[DialogueLineDraft] = Field(default_factory=list)
    clips: list[ClipScript] = Field(default_factory=list)


class ShotDraft(BaseModel):
    shot_id: str
    index_in_scene: int
    story_order: int
    covers_event_ids: list[str] = Field(default_factory=list)
    duration_s: float = 5.0
    location_id: str
    cast: list[CastInShot] = Field(default_factory=list)
    prop_ids: list[str] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    look: ShotLook | None = None
    clip_index: int | None = None
    beats: list[ActionBeat] = Field(default_factory=list)
    dialogue_ids: list[str] = Field(default_factory=list)
    entry_motion_vector: str = "stationary"
    exit_motion_vector: str = "stationary"
    continue_from_last_frame: bool = False


class DirectorSceneOutput(BaseModel):
    shots: list[ShotDraft] = Field(default_factory=list)


class MusicCueDraft(BaseModel):
    cue_id: str
    scene_id: str
    mood: str
    instrumentation: str
    tempo_bpm: int = 92
    motif_tags: list[str] = Field(default_factory=list)
    environmental_bed: str = ""


class ShotAudioDraft(BaseModel):
    shot_id: str
    music_cue_id: str | None = None
    sfx: list[str] = Field(default_factory=list)
    foley_sfx: list[str] = Field(default_factory=list)
    environmental_sfx: list[str] = Field(default_factory=list)
    action_focus_sfx: list[str] = Field(default_factory=list)


class MusicDirectorOutput(BaseModel):
    cues: list[MusicCueDraft] = Field(default_factory=list)
    shot_audio: list[ShotAudioDraft] = Field(default_factory=list)

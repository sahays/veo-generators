"""Complete Pydantic schema models for all 6 layers of the Story-to-Video Graph."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Role(StrEnum):
    STORY_ARCHITECT = "story_architect"
    SCRIPT_SUPERVISOR = "script_supervisor"
    SCREENWRITER = "screenwriter"
    CHARACTER_DESIGNER = "character_designer"
    LOCATION_DESIGNER = "location_designer"
    OBJECT_DESIGNER = "object_designer"
    DESIGNER = "designer"
    DIRECTOR = "director"
    MUSIC_DIRECTOR = "music_director"
    CRITIC = "critic"
    PIPELINE = "pipeline"
    HUMAN = "human"


class EntityType(StrEnum):
    CHARACTER = "character"
    LOCATION = "location"
    OBJECT = "object"


class Provenance(StrEnum):
    FROM_TEXT = "from_text"
    INFERRED = "inferred"
    INVENTED = "invented"


class Status(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    FAILED = "failed"
    RENDERED = "rendered"


class NodeBase(BaseModel):
    id: str
    node_type: str
    version: int = 1
    status: Status = Status.DRAFT
    created_by: Role
    created_at: datetime = Field(default_factory=_utc_now)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Identity
# ─────────────────────────────────────────────────────────────────────────────


class AttributeVal(BaseModel):
    value: str
    provenance: Provenance
    source_span: tuple[int, int] | None = None


class Entity(NodeBase):
    node_type: Literal["Entity"] = "Entity"
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, AttributeVal] = Field(default_factory=dict)
    voice_profile_id: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Narrative Events & State
# ─────────────────────────────────────────────────────────────────────────────


class StateEffect(BaseModel):
    entity_id: str
    attribute: Literal[
        "location", "holding", "wearing", "injury", "mood", "alive_present"
    ]
    new_value: str | None  # None = cleared


class Event(NodeBase):
    node_type: Literal["Event"] = "Event"
    story_order: int
    scene_id: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)
    source_span: tuple[int, int] = (0, 0)


class StateFact(NodeBase):
    """Derived by `state.rebuild_state_facts` — never written by an LLM."""

    node_type: Literal["StateFact"] = "StateFact"
    entity_id: str
    attribute: str
    value: str
    valid_from_order: int
    valid_to_order: int | None = None
    caused_by_event_id: str
    derived: Literal[True] = True


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Appearance & Visual Assets
# ─────────────────────────────────────────────────────────────────────────────


class Appearance(NodeBase):
    node_type: Literal["Appearance"] = "Appearance"
    entity_id: str
    state_label: str  # e.g. "default", "rain_soaked", "Formal_Suit"
    visual_description: str
    wardrobe: str | None = None
    condition_tags: list[str] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    supersedes: str | None = None


class Asset(NodeBase):
    node_type: Literal["Asset"] = "Asset"
    kind: Literal[
        "character_sheet",
        "location_plate",
        "prop_sheet",
        "composite_sheet",
        "first_frame",
        "audio",
    ]
    uri: str
    signed_url: str | None = None
    sha256: str
    depicts_entity_ids: list[str] = Field(default_factory=list)
    appearance_ids: list[str] = Field(default_factory=list)
    generation_prompt: str
    seed: int | None = None
    model: str
    qa_notes: str | None = None
    supersedes: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 — Screenplay & Shots
# ─────────────────────────────────────────────────────────────────────────────


class StyleGuide(NodeBase):
    node_type: Literal["StyleGuide"] = "StyleGuide"
    visual_medium: str
    palette: list[str] = Field(default_factory=list)
    lens_language: str
    lighting_rules: str
    aspect_ratio: Literal["16:9", "9:16", "2.39:1"] = "16:9"
    fps: int = 24
    avoid: list[str] = Field(default_factory=list)


class Scene(NodeBase):
    node_type: Literal["Scene"] = "Scene"
    index: int
    heading: str
    location_id: str
    time_of_day: str
    weather: str = "clear"
    event_ids: list[str] = Field(default_factory=list)
    shot_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    mood: str = ""


class DialogueLine(NodeBase):
    node_type: Literal["DialogueLine"] = "DialogueLine"
    scene_id: str
    shot_id: str | None = None
    order_in_scene: int
    speaker_id: str
    addressee_id: str | None = None
    text: str
    delivery: str = "natural"
    language: str = "en"


class MusicCue(NodeBase):
    node_type: Literal["MusicCue"] = "MusicCue"
    scene_id: str
    mood: str
    instrumentation: str
    tempo_bpm: int
    motif_tags: list[str] = Field(default_factory=list)
    audio_asset_id: str | None = None


class CastInShot(BaseModel):
    entity_id: str
    appearance_id: str = ""  # resolved deterministically on write
    position: Literal[
        "left", "center", "right", "foreground", "background", "offscreen_voice"
    ] = "center"
    framing: Literal["ECU", "CU", "MCU", "MS", "WS", "OS"] = "MS"
    speaking: bool = False


class ActionBeat(BaseModel):
    t_start_s: float
    t_end_s: float
    description: str
    subject_ids: list[str] = Field(default_factory=list)


class CameraSpec(BaseModel):
    shot_size: Literal["ECU", "CU", "MCU", "MS", "MLS", "WS", "EWS"] = "MS"
    angle: Literal["eye", "low", "high", "dutch", "overhead", "pov"] = "eye"
    movement: Literal[
        "static",
        "pan_l",
        "pan_r",
        "tilt_up",
        "tilt_down",
        "dolly_in",
        "dolly_out",
        "track",
        "handheld",
    ] = "static"
    lens_mm: int = 35
    focus_target_id: str | None = None


class Shot(NodeBase):
    node_type: Literal["Shot"] = "Shot"
    scene_id: str
    index_in_scene: int
    story_order: int
    covers_event_ids: list[str] = Field(default_factory=list)
    duration_s: float
    location_id: str
    location_appearance_id: str = ""
    cast: list[CastInShot] = Field(default_factory=list)
    prop_ids: list[str] = Field(default_factory=list)
    prop_appearance_ids: dict[str, str] = Field(default_factory=dict)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    beats: list[ActionBeat] = Field(default_factory=list)
    dialogue_ids: list[str] = Field(default_factory=list)
    music_cue_id: str | None = None
    sfx: list[str] = Field(default_factory=list)
    continue_from_last_frame: bool = False
    ref_ids: list[str] = Field(default_factory=list)  # denormalized appearance IDs
    stale: bool = False
    stale_reason: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5 — Generation & QA
# ─────────────────────────────────────────────────────────────────────────────


class QAReport(BaseModel):
    face_similarity: dict[str, float] = Field(default_factory=dict)
    wardrobe_match: float = 1.0
    setting_match: float = 1.0
    action_achieved: float = 1.0
    continuity_prev_shot: float = 1.0
    dialogue_wer: float = 0.0
    artifact_flags: list[str] = Field(default_factory=list)
    passed: bool = True
    failure_reasons: list[str] = Field(default_factory=list)
    suggested_fix: Literal[
        "none", "retry_seed", "recompile_prompt", "resplit_shot", "redesign_asset"
    ] = "none"


class GenerationRun(NodeBase):
    node_type: Literal["GenerationRun"] = "GenerationRun"
    shot_id: str
    attempt: int
    provider: str
    model: str
    compiled_prompt: str
    negative_prompt: str = ""
    reference_asset_ids: list[str] = Field(default_factory=list)
    first_frame_asset_id: str | None = None
    seed: int
    package_hash: str
    output_video_uri: str | None = None
    output_video_signed_url: str | None = None
    extracted_last_frame_asset_id: str | None = None
    qa_scores: QAReport | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Layer 6 — Governance
# ─────────────────────────────────────────────────────────────────────────────


class ChangeRequest(NodeBase):
    node_type: Literal["ChangeRequest"] = "ChangeRequest"
    from_role: Role
    to_role: Role
    target_node_id: str
    reason: str
    proposed_patch: dict[str, Any] = Field(default_factory=dict)
    resolution: Literal["open", "accepted", "rejected"] = "open"


class Gate(NodeBase):
    node_type: Literal["Gate"] = "Gate"
    gate_id: Literal["G1", "G2", "G3"]
    stage: str
    decision: Literal["pending", "approved", "rejected"] = "pending"
    reviewer: str | None = None
    notes: str | None = None
    decided_at: datetime | None = None


class StageRun(NodeBase):
    node_type: Literal["StageRun"] = "StageRun"
    stage: str
    input_hash: str
    completed: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    error: str | None = None


class AuditEntry(NodeBase):
    node_type: Literal["AuditEntry"] = "AuditEntry"
    role: Role
    tool: str
    target_id: str
    before_version: int | None = None
    after_version: int
    summary: str = ""


class ProjectMeta(BaseModel):
    """Top-level project metadata stored at projects/{project_id}."""

    id: str
    name: str
    type: Literal["movie", "advertizement", "social"] = "movie"
    base_concept: str
    story_text: str = ""
    video_length: str = "16"
    orientation: Literal["16:9", "9:16"] = "16:9"
    language: str = "en-IN"
    auto_approve_gates: bool = False
    status: str = "draft"
    current_stage: str = "S0_INGEST"
    final_video_uri: str | None = None
    final_video_url: str | None = None
    invite_code: str | None = None
    archived: bool = False
    error_message: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


ALL_NODE_TYPES: dict[str, type[NodeBase]] = {
    "Entity": Entity,
    "Event": Event,
    "StateFact": StateFact,
    "Appearance": Appearance,
    "Asset": Asset,
    "StyleGuide": StyleGuide,
    "Scene": Scene,
    "DialogueLine": DialogueLine,
    "MusicCue": MusicCue,
    "Shot": Shot,
    "GenerationRun": GenerationRun,
    "ChangeRequest": ChangeRequest,
    "Gate": Gate,
    "StageRun": StageRun,
    "AuditEntry": AuditEntry,
}

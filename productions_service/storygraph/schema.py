"""Complete Pydantic schema models for all 6 layers of the Story-to-Video Graph."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .clips.models import ClipScript, ShotLook
from .schemas.base import (  # noqa: F401 - re-exported public API
    EntityType,
    NodeBase,
    Provenance,
    Role,
    Status,
    _utc_now,
)
from .schemas.generation import (  # noqa: F401 - re-exported public API
    ClipTrim,
    DimensionScore,
    GenerationRun,
    PatchOp,
    PromptVersion,
    PromptVersionAuthor,
    PromptVersionStatus,
    QADefect,
    QAReport,
)

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
        "location",
        "sub_location",
        "supported_by",
        "orientation",
        "holding",
        "wearing",
        "injury",
        "mood",
        "alive_present",
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


class InteractionStep(BaseModel):
    """Atomic 1-action-at-a-time algorithmic screenplay step with Hoare-triple physical state."""

    step_index: int
    actor_id: str
    interaction_type: Literal["character", "prop", "environment"] = "environment"
    target_id: str | None = None
    target_kind: Literal["character", "prop", "environment"] = "environment"
    verb: str = "acts"
    action_verb: str = "acts"
    action: str = ""
    description: str = ""
    detail: str = ""
    pre_state: str = ""
    contact_mechanics: str = ""
    post_state: str = ""
    supported_by: str = ""
    spatial_note: str = "center frame"
    emotional_beat: str = "focused"
    environment_reaction: str = ""
    sound_trigger: str = ""
    duration_hint_s: float = 2.0

    def model_post_init(self, __context: Any) -> None:
        if self.action and not self.description:
            object.__setattr__(self, "description", self.action)
        elif self.description and not self.action:
            object.__setattr__(self, "action", self.description)
        if self.interaction_type != "environment" and self.target_kind == "environment":
            object.__setattr__(self, "target_kind", self.interaction_type)


class StyleGuide(NodeBase):
    node_type: Literal["StyleGuide"] = "StyleGuide"
    visual_medium: str
    palette: list[str] = Field(default_factory=list)
    lens_language: str
    lighting_rules: str
    aspect_ratio: Literal["16:9", "9:16", "2.39:1"] = "16:9"
    fps: int = 24
    avoid: list[str] = Field(default_factory=list)
    visual_style_preset: str = "pixar_3d"
    color_palette_preset: str = "warm_golden_amber"
    director_style_preset: str = "wonder_spectacle"
    screenplay_style_preset: str = "algorithmic_wonder"
    music_style_preset: str = "symphonic_leitmotif"


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
    interaction_steps: list[InteractionStep] = Field(default_factory=list)
    clips: list[ClipScript] = Field(default_factory=list)  # screenwriter-owned


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
    environmental_bed: str = ""
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
    pre_state: str = ""
    post_state: str = ""


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


class ShotLintIssue(BaseModel):
    """A validation / spec-linter finding attached to its shot, for UI display.

    `status="auto_fixed"` records a deterministic remediation (`fix` says what changed);
    `status="open"` is still blocking and was routed to `route` (S2 screenwriter / S4 director);
    `status="demoted"` survived every remediation round and was downgraded to a warning so
    the pipeline continues (`fix` says why). `source` is the stage that recorded it.
    """

    code: str
    message: str
    route: Literal["S2", "S4"]
    severity: Literal["error", "warn"] = "error"
    status: Literal["open", "auto_fixed", "demoted"] = "open"
    fix: str = ""
    source: Literal["S6", "S7"] = "S7"


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
    look: ShotLook | None = None  # director-owned cinematography look
    clip_index: int | None = None  # 1:1 link to Scene.clips[*].clip_index
    beats: list[ActionBeat] = Field(default_factory=list)
    dialogue_ids: list[str] = Field(default_factory=list)
    music_cue_id: str | None = None
    sfx: list[str] = Field(default_factory=list)
    foley_sfx: list[str] = Field(default_factory=list)
    environmental_sfx: list[str] = Field(default_factory=list)
    action_focus_sfx: list[str] = Field(default_factory=list)
    entry_motion_vector: str = "stationary"
    exit_motion_vector: str = "stationary"
    continue_from_last_frame: bool = False
    ref_ids: list[str] = Field(default_factory=list)  # denormalized appearance IDs
    stale: bool = False
    stale_reason: str | None = None
    content_hash: str | None = None  # render-relevant fingerprint (None = legacy)
    # Automatic QA-repair bookkeeping for the current content version (reset on edit).
    repair_attempts: int = 0
    needs_manual_edit: bool = False
    manual_edit_reasons: list[str] = Field(default_factory=list)
    # Spec-linter findings from the latest S7 pass (not render content: excluded from hash).
    lint_issues: list[ShotLintIssue] = Field(default_factory=list)


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


class StageQaIssue(BaseModel):
    code: str
    severity: Literal["error", "warn"] = "error"
    node_id: str = "graph"
    dimension: str = "general"
    message: str
    remediation: str = ""


class StageQaReport(NodeBase):
    node_type: Literal["StageQaReport"] = "StageQaReport"
    stage: str
    agent_role: str = "critic"
    target_role: str = ""
    attempt: int = 1
    iteration: int = 1
    passed: bool = True
    score: float = 1.0
    issues: list[StageQaIssue] = Field(default_factory=list)
    remediation_applied: list[str] = Field(default_factory=list)
    summary: str = ""


class ProjectMeta(BaseModel):
    """Top-level project metadata stored at projects/{project_id}."""

    id: str
    name: str
    type: Literal["movie", "advertizement", "social"] = "movie"
    base_concept: str = ""
    story_text: str = ""
    video_length: str = "16"
    orientation: Literal["16:9", "9:16"] = "16:9"
    language: str = "en-IN"
    visual_style_preset: str = "pixar_3d"
    color_palette_preset: str = "warm_golden_amber"
    director_style_preset: str = "wonder_spectacle"
    screenplay_style_preset: str = "algorithmic_wonder"
    music_style_preset: str = "symphonic_leitmotif"
    auto_approve_gates: bool = True
    render_quality: Literal["draft", "final"] = "draft"
    video_resolution: Literal["360p", "720p"] = "360p"
    status: str = "draft"
    current_stage: str = "S0_INGEST"
    final_video_uri: str | None = None
    final_video_url: str | None = None
    invite_code: str | None = None
    archived: bool = False
    error_message: str | None = None
    skipped_shot_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


ALL_NODE_TYPES: dict[str, type[NodeBase]] = {
    cls.__name__: cls for cls in NodeBase.__subclasses__()
}

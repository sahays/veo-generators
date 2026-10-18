"""Project/Scene models used by the production pipeline."""

from datetime import datetime

from models_core import (
    ProjectStatus,
    SystemResourceInfo,
    UsageMetrics,
    generate_id,
)
from pydantic import BaseModel, Field


class GlobalStyle(BaseModel):
    look: str | None = None
    mood: str | None = None
    color_grading: str | None = None
    lighting_style: str | None = None
    pace: str | None = None
    soundtrack_style: str | None = None


class CharacterProfile(BaseModel):
    id: str
    description: str
    wardrobe: str | None = None


class Continuity(BaseModel):
    characters: list[CharacterProfile] = []
    setting_notes: str | None = None


class SceneMetadata(BaseModel):
    location: str | None = None
    characters: list[str] = []
    camera_angle: str | None = None
    camera_movement: str | None = None
    lighting: str | None = None
    cinematic_style: str | None = None
    pace: str | None = None
    style: str | None = None
    mood: str | None = None


class PipelineStepLog(BaseModel):
    step_id: str
    label: str
    status: str = "pending"  # pending, running, completed, skipped, failed
    detail: str = ""
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class StoryboardReviewIssue(BaseModel):
    scene_number: int = 0
    category: str = "continuity"
    severity: str = "warning"  # critical, warning
    problem: str
    fix_applied: str


class StoryboardReviewReport(BaseModel):
    overall_score: int = 100
    summary: str = ""
    issues: list[StoryboardReviewIssue] = []
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    reviewed_at: datetime | None = None


class SceneEvalFinding(BaseModel):
    scene_number: int
    scene_id: str | None = None
    category: str = "continuity"
    severity: str = "critical"  # critical, warning
    observed_issue: str
    regenerate_frame: bool = False
    regenerate_video: bool = True
    corrected_visual_description: str | None = None
    corrected_speaker_notes: str | None = None
    corrected_narration: str | None = None
    corrected_music_description: str | None = None


class VideoEvalReport(BaseModel):
    overall_score: int = 100
    passed: bool = True
    iteration: int = 1
    summary: str = ""
    findings: list[SceneEvalFinding] = []
    regenerated_scene_ids: list[str] = []
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    evaluated_at: datetime | None = None


class Scene(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("s-"))
    visual_description: str
    narration: str | None = None
    narration_enabled: bool = False
    speaker_notes: str | None = None
    music_description: str | None = None
    music_enabled: bool = False
    timestamp_start: str
    timestamp_end: str
    metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    enter_transition: str | None = None
    exit_transition: str | None = None
    music_transition: str | None = None
    thumbnail_url: str | None = None
    end_frame_url: str | None = None
    video_url: str | None = None
    video_resolution: str | None = None
    generated_prompt: str | None = None
    image_prompt: str | None = None
    end_frame_prompt: str | None = None
    video_prompt: str | None = None
    operation_name: str | None = None
    status: str = "pending"  # pending, generating, completed, failed
    eval_status: str | None = None  # passed, flagged, regenerating, regenerated
    eval_feedback: str | None = None
    regen_count: int = 0
    error_message: str | None = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("p-"))
    name: str
    type: str = "advertizement"  # movie, advertizement, social
    base_concept: str
    video_length: str = "16"
    orientation: str = "16:9"  # 16:9, 9:16
    language: str = "en-IN"  # en-IN (English India), hi-IN (Hindi), en-US (English US)
    visual_style_preset: str | None = "pixar_3d"
    color_palette_preset: str | None = "warm_golden_amber"
    director_style_preset: str | None = "wonder_spectacle"
    screenplay_style_preset: str | None = "algorithmic_wonder"
    music_style_preset: str | None = "symphonic_leitmotif"
    render_quality: str = "draft"  # draft, final
    video_resolution: str = "360p"  # 360p, 720p, 1080p
    status: ProjectStatus = ProjectStatus.DRAFT
    current_stage: str | None = None
    pipeline_stage: str | None = None
    pipeline_steps: list[PipelineStepLog] = []
    prompt_info: SystemResourceInfo | None = None
    schema_info: SystemResourceInfo | None = None
    reference_image_url: str | None = None
    draft_video_url: str | None = None
    final_video_url: str | None = None
    stitch_job_name: str | None = None
    global_style: GlobalStyle | None = None
    continuity: Continuity | None = None
    analysis_prompt: str | None = None
    review_report: StoryboardReviewReport | None = None
    eval_report: VideoEvalReport | None = None
    error_message: str | None = None
    signed_urls: dict = Field(default_factory=dict)
    scenes: list[Scene] = []
    archived: bool = False
    invite_code: str | None = None
    total_usage: UsageMetrics = Field(default_factory=UsageMetrics)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

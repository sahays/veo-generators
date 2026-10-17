"""Project/Scene models used by the production pipeline."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from models_core import (
    ProjectStatus,
    SystemResourceInfo,
    UsageMetrics,
    generate_id,
)


class GlobalStyle(BaseModel):
    look: Optional[str] = None
    mood: Optional[str] = None
    color_grading: Optional[str] = None
    lighting_style: Optional[str] = None
    pace: Optional[str] = None
    soundtrack_style: Optional[str] = None


class CharacterProfile(BaseModel):
    id: str
    description: str
    wardrobe: Optional[str] = None


class Continuity(BaseModel):
    characters: List[CharacterProfile] = []
    setting_notes: Optional[str] = None


class SceneMetadata(BaseModel):
    location: Optional[str] = None
    characters: List[str] = []
    camera_angle: Optional[str] = None
    camera_movement: Optional[str] = None
    lighting: Optional[str] = None
    cinematic_style: Optional[str] = None
    pace: Optional[str] = None
    style: Optional[str] = None
    mood: Optional[str] = None


class PipelineStepLog(BaseModel):
    step_id: str
    label: str
    status: str = "pending"  # pending, running, completed, skipped, failed
    detail: str = ""
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class StoryboardReviewIssue(BaseModel):
    scene_number: int = 0
    category: str = "continuity"
    severity: str = "warning"  # critical, warning
    problem: str
    fix_applied: str


class StoryboardReviewReport(BaseModel):
    overall_score: int = 100
    summary: str = ""
    issues: List[StoryboardReviewIssue] = []
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    reviewed_at: Optional[datetime] = None


class SceneEvalFinding(BaseModel):
    scene_number: int
    scene_id: Optional[str] = None
    category: str = "continuity"
    severity: str = "critical"  # critical, warning
    observed_issue: str
    regenerate_frame: bool = False
    regenerate_video: bool = True
    corrected_visual_description: Optional[str] = None
    corrected_speaker_notes: Optional[str] = None
    corrected_narration: Optional[str] = None
    corrected_music_description: Optional[str] = None


class VideoEvalReport(BaseModel):
    overall_score: int = 100
    passed: bool = True
    iteration: int = 1
    summary: str = ""
    findings: List[SceneEvalFinding] = []
    regenerated_scene_ids: List[str] = []
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    evaluated_at: Optional[datetime] = None


class Scene(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("s-"))
    visual_description: str
    narration: Optional[str] = None
    narration_enabled: bool = False
    speaker_notes: Optional[str] = None
    music_description: Optional[str] = None
    music_enabled: bool = False
    timestamp_start: str
    timestamp_end: str
    metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    enter_transition: Optional[str] = None
    exit_transition: Optional[str] = None
    music_transition: Optional[str] = None
    thumbnail_url: Optional[str] = None
    end_frame_url: Optional[str] = None
    video_url: Optional[str] = None
    video_resolution: Optional[str] = None
    generated_prompt: Optional[str] = None
    image_prompt: Optional[str] = None
    end_frame_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    operation_name: Optional[str] = None
    status: str = "pending"  # pending, generating, completed, failed
    eval_status: Optional[str] = None  # passed, flagged, regenerating, regenerated
    eval_feedback: Optional[str] = None
    regen_count: int = 0
    error_message: Optional[str] = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("p-"))
    name: str
    type: str = "advertizement"  # movie, advertizement, social
    base_concept: str
    video_length: str = "16"
    orientation: str = "16:9"  # 16:9, 9:16
    language: str = "en-IN"  # en-IN (English India), hi-IN (Hindi), en-US (English US)
    render_quality: str = "draft"  # draft, final
    video_resolution: str = "360p"  # 360p, 720p, 1080p
    status: ProjectStatus = ProjectStatus.DRAFT
    pipeline_stage: Optional[str] = None
    pipeline_steps: List[PipelineStepLog] = []
    prompt_info: Optional[SystemResourceInfo] = None
    schema_info: Optional[SystemResourceInfo] = None
    reference_image_url: Optional[str] = None
    draft_video_url: Optional[str] = None
    final_video_url: Optional[str] = None
    stitch_job_name: Optional[str] = None
    global_style: Optional[GlobalStyle] = None
    continuity: Optional[Continuity] = None
    analysis_prompt: Optional[str] = None
    review_report: Optional[StoryboardReviewReport] = None
    eval_report: Optional[VideoEvalReport] = None
    error_message: Optional[str] = None
    signed_urls: dict = Field(default_factory=dict)
    scenes: List[Scene] = []
    archived: bool = False
    invite_code: Optional[str] = None
    total_usage: UsageMetrics = Field(default_factory=UsageMetrics)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

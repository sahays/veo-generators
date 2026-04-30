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


class Scene(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("s-"))
    visual_description: str
    narration: Optional[str] = None
    narration_enabled: bool = False
    music_description: Optional[str] = None
    music_enabled: bool = False
    timestamp_start: str
    timestamp_end: str
    metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    enter_transition: Optional[str] = None
    exit_transition: Optional[str] = None
    music_transition: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    generated_prompt: Optional[str] = None
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    operation_name: Optional[str] = None
    status: str = "pending"  # pending, generating, completed, failed
    error_message: Optional[str] = None
    usage: UsageMetrics = Field(default_factory=UsageMetrics)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("p-"))
    name: str
    type: str = "advertizement"  # movie, advertizement, social
    base_concept: str
    video_length: str = "16"
    orientation: str = "16:9"  # 16:9, 9:16
    status: ProjectStatus = ProjectStatus.DRAFT
    prompt_info: Optional[SystemResourceInfo] = None
    schema_info: Optional[SystemResourceInfo] = None
    reference_image_url: Optional[str] = None
    final_video_url: Optional[str] = None
    stitch_job_name: Optional[str] = None
    global_style: Optional[GlobalStyle] = None
    continuity: Optional[Continuity] = None
    analysis_prompt: Optional[str] = None
    error_message: Optional[str] = None
    signed_urls: dict = Field(default_factory=dict)
    scenes: List[Scene] = []
    archived: bool = False
    invite_code: Optional[str] = None
    total_usage: UsageMetrics = Field(default_factory=UsageMetrics)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

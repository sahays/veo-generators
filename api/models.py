import random
import string
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime
from enum import Enum


def generate_id(prefix: str) -> str:
    chars = string.ascii_lowercase + string.digits
    return f"{prefix}{''.join(random.choice(chars) for _ in range(8))}"


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    SCRIPTED = "scripted"
    GENERATING = "generating"
    STITCHING = "stitching"
    COMPLETED = "completed"
    FAILED = "failed"


class SystemResourceType(str, Enum):
    PROMPT = "prompt"
    SCHEMA = "schema"


class SystemResourceInfo(BaseModel):
    id: str
    name: str
    version: int


class SystemResource(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("res-"))
    type: SystemResourceType
    category: str  # e.g. project-analysis
    name: str
    version: int = 1
    content: str
    is_active: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class UsageMetrics(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: str = ""
    cost_usd: float = 0.0


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
    total_usage: UsageMetrics = Field(default_factory=UsageMetrics)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)


class KeyMomentModel(BaseModel):
    title: str
    description: str
    timestamp_start: str
    timestamp_end: str
    category: Optional[str] = None
    tags: List[str] = []


class KeyMomentsRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("km-"))
    video_gcs_uri: str
    video_filename: str = ""
    video_source: str = "upload"  # "upload" | "production"
    production_id: Optional[str] = None
    mime_type: str = "video/mp4"
    prompt_id: str = ""
    video_summary: Optional[str] = None
    key_moments: List[KeyMomentModel] = []
    moment_count: int = 0
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class ThumbnailScreenshot(BaseModel):
    timestamp: str
    title: str
    description: str
    visual_characteristics: str = ""
    category: Optional[str] = None
    tags: List[str] = []
    gcs_uri: str = ""


class ThumbnailRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("th-"))
    video_gcs_uri: str
    video_filename: str = ""
    video_source: str = "upload"  # "upload" | "production"
    production_id: Optional[str] = None
    mime_type: str = "video/mp4"
    analysis_prompt_id: str = ""
    collage_prompt_id: str = ""
    video_summary: Optional[str] = None
    screenshots: List[ThumbnailScreenshot] = []
    thumbnail_gcs_uri: Optional[str] = None
    status: str = "analyzing"  # analyzing | screenshots_ready | generating | completed
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class CompressedVariant(BaseModel):
    resolution: str  # "480p" | "720p"
    gcs_uri: str = ""
    job_name: str = ""
    status: str = "pending"  # pending | processing | succeeded | failed
    child_upload_id: Optional[str] = None


class UploadRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("up-"))
    filename: str
    mime_type: str
    file_type: str = "other"  # "video" | "image" | "other"
    gcs_uri: str
    file_size_bytes: int = 0
    compressed_variants: List[CompressedVariant] = []
    parent_upload_id: Optional[str] = None
    resolution_label: Optional[str] = None
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class AIResponseWrapper(BaseModel):
    data: Any
    usage: UsageMetrics

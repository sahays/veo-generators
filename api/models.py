import random
import string
from pydantic import BaseModel, Field
from typing import List, Optional, Any
from datetime import datetime
from enum import Enum

def generate_id(prefix: str) -> str:
    chars = string.ascii_letters + string.digits
    return f"{prefix}{''.join(random.choice(chars) for _ in range(8))}"

class ProjectStatus(str, Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    SCRIPTED = "scripted"
    GENERATING = "generating"
    STITCHING = "stitching"
    COMPLETED = "completed"
    FAILED = "failed"

class UsageMetrics(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: str = ""
    cost_usd: float = 0.0

class SceneMetadata(BaseModel):
    location: Optional[str] = None
    character: Optional[str] = None
    camera_angle: Optional[str] = None
    lighting: Optional[str] = None
    style: Optional[str] = None
    mood: Optional[str] = None

class Scene(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("s-"))
    visual_description: str
    timestamp_start: str
    timestamp_end: str
    metadata: SceneMetadata = Field(default_factory=SceneMetadata)
    thumbnail_url: Optional[str] = None
    video_url: Optional[str] = None
    status: str = "pending" # pending, generating, completed, failed
    usage: UsageMetrics = Field(default_factory=UsageMetrics)

class Project(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("p-"))
    name: str
    type: str = "advertizement" # movie, advertizement, social
    base_concept: str
    video_length: str = "16"
    orientation: str = "16:9" # 16:9, 9:16
    status: ProjectStatus = ProjectStatus.DRAFT
    reference_image_url: Optional[str] = None
    final_video_url: Optional[str] = None
    scenes: List[Scene] = []
    total_usage: UsageMetrics = Field(default_factory=UsageMetrics)
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

class AIResponseWrapper(BaseModel):
    data: Any
    usage: UsageMetrics

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class ProjectStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"

class MediaFile(BaseModel):
    id: str
    gcs_uri: str
    preview_url: Optional[str] = None
    file_type: str # image or video

class StoryboardFrame(BaseModel):
    id: str
    image_url: str
    caption: str
    timestamp: str

class Project(BaseModel):
    id: str
    name: str
    prompt: str
    refined_prompt: Optional[str] = None
    director_style: Optional[str] = None
    camera_movement: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    character_appearance: Optional[str] = None
    video_length: str = "16"
    status: ProjectStatus = ProjectStatus.DRAFT
    media_files: List[MediaFile] = []
    storyboard_frames: List[StoryboardFrame] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class OptimizePromptRequest(BaseModel):
    raw_prompt: str
    director_style: Optional[str] = None
    mood: Optional[str] = None
    location: Optional[str] = None
    camera_movement: Optional[str] = None

class OptimizePromptResponse(BaseModel):
    refined_prompt: str

class GenerateStoryboardRequest(BaseModel):
    project_id: str
    refined_prompt: str

class GenerateVideoRequest(BaseModel):
    project_id: str
    refined_prompt: str
    video_length: str

class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    output_uri: Optional[str] = None
    error_message: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)

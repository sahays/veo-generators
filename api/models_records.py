"""Feature records: key moments, thumbnails, reframe, promo, adapts."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from models_core import UsageMetrics, generate_id


# ── Key Moments ──────────────────────────────────────────────────────


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
    display_name: str = ""
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
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)


# ── Thumbnails ───────────────────────────────────────────────────────


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
    display_name: str = ""
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
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)


# ── Reframe ──────────────────────────────────────────────────────────


class FocalPoint(BaseModel):
    time_sec: float
    x: float  # 0.0-1.0 horizontal position
    y: float  # 0.0-1.0 vertical position
    confidence: float = 1.0
    description: str = ""


class SceneChange(BaseModel):
    time_sec: float
    description: str = ""


class SpeakerPosition(BaseModel):
    speaker_id: str
    x: float  # 0.0-1.0 horizontal position
    y: float  # 0.0-1.0 vertical position
    description: str = ""


class SpeakerSegment(BaseModel):
    speaker_id: str
    start_sec: float
    end_sec: float
    confidence: float = 1.0


class ReframeRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("rf-"))
    source_gcs_uri: str
    source_filename: str = ""
    display_name: str = ""
    prompt_id: str = ""
    content_type: str = "other"
    blurred_bg: bool = False
    sports_mode: bool = False
    vertical_split: bool = False
    model_id: Optional[str] = None
    region: Optional[str] = None
    output_gcs_uri: Optional[str] = None
    focal_points: List[FocalPoint] = []
    scene_changes: List[SceneChange] = []
    speaker_positions: List[SpeakerPosition] = []
    speaker_segments: List[SpeakerSegment] = []
    prompt_variables: dict = Field(default_factory=dict)
    prompt_text_used: str = ""
    track_summary: str = ""
    gemini_scenes: list = Field(default_factory=list)
    status: str = "pending"  # pending|analyzing|processing|encoding|completed|failed
    error_message: Optional[str] = None
    progress_pct: int = 0
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None


# ── Promo ────────────────────────────────────────────────────────────


class PromoSegment(BaseModel):
    title: str
    description: str
    timestamp_start: str  # MM:SS or HH:MM:SS
    timestamp_end: str
    order: int = 0
    relevance_score: float = 0.0
    overlay_gcs_uri: Optional[str] = None


class PromoRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("prm-"))
    source_gcs_uri: str
    source_filename: str = ""
    display_name: str = ""
    prompt_id: str = ""
    target_duration: int = 60  # seconds
    text_overlay: bool = False
    generate_thumbnail: bool = False
    model_id: Optional[str] = None
    region: Optional[str] = None
    thumbnail_gcs_uri: Optional[str] = None
    segments: List[PromoSegment] = []
    output_gcs_uri: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    progress_pct: int = 0
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None


# ── Adapts ───────────────────────────────────────────────────────────


class AdaptVariant(BaseModel):
    aspect_ratio: str  # e.g. "16:9", "9:16", "1:1", "4:3", "4:5", "3:4"
    status: str = "pending"  # pending | generating | completed | failed
    output_gcs_uri: Optional[str] = None
    prompt_text_used: Optional[str] = None
    error_message: Optional[str] = None


class AdaptRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("adp-"))
    source_gcs_uri: str
    source_filename: str = ""
    source_mime_type: str = "image/png"
    display_name: str = ""
    template_gcs_uri: Optional[str] = None
    prompt_id: str = ""
    preset_bundle: str = ""
    model_id: Optional[str] = None
    region: Optional[str] = None
    variants: List[AdaptVariant] = []
    status: str = "pending"  # pending|generating|completed|partial|failed
    error_message: Optional[str] = None
    progress_pct: int = 0
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None

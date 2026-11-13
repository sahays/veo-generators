"""Video insight records: scene analysis timelines and engagement reports.

Both records are job documents (status / stage / progress) whose heavy payloads
(`timeline.json`, `report.json`) live in GCS; Firestore keeps only summaries.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from models_core import UsageMetrics, generate_id

TIMELINE_SCHEMA_VERSION = "video-timeline-v1"
ENGAGEMENT_REPORT_VERSION = "engagement-report-v1"


class FilmstripSpec(BaseModel):
    """Layout of the single sprite image used by the timeline thumbnail lane."""

    tile_width: int
    tile_height: int
    columns: int
    rows: int
    interval_sec: float
    count: int


class SceneAnalysisRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("sa-"))
    source_type: str = "upload"  # "upload" | "production"
    source_id: str
    video_gcs_uri: str
    video_filename: str = ""
    display_name: str = ""
    mime_type: str = "video/mp4"
    focus: str = ""  # optional user guidance, passed to the model as data
    model_id: Optional[str] = None
    region: Optional[str] = None
    status: str = "pending"  # pending|analyzing|processing|completed|failed
    stage: str = ""  # probe|analyze|merge|filmstrip
    stage_detail: str = ""  # e.g. "window 2 of 5"
    progress_pct: int = 0
    error_message: Optional[str] = None
    duration_sec: float = 0.0
    window_count: int = 0
    summary: str = ""
    content_title: str = ""
    counts: dict = Field(default_factory=dict)  # per-collection item counts
    timeline_gcs_uri: Optional[str] = None
    filmstrip_gcs_uri: Optional[str] = None
    filmstrip: Optional[FilmstripSpec] = None
    schema_version: str = TIMELINE_SCHEMA_VERSION
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None


class EngagementSignalSpec(BaseModel):
    """Where the engagement curve comes from: a built-in template or a BARC CSV."""

    kind: str = "template"  # "template" | "barc"
    template_id: Optional[str] = None  # high|low|jumpy|slow_burn|front_loaded
    upload_id: Optional[str] = None  # UploadRecord id of the BARC CSV
    csv_gcs_uri: Optional[str] = None  # resolved server-side from upload_id
    csv_filename: str = ""
    time_column: Optional[str] = None
    metric: Optional[str] = None  # primary metric column
    offset_sec: float = 0.0  # shift applied to align the CSV with video t=0


class EngagementRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("en-"))
    scene_analysis_id: str
    source_type: str = "upload"  # "upload" | "production"
    source_id: str
    video_gcs_uri: str
    video_filename: str = ""
    display_name: str = ""
    mime_type: str = "video/mp4"
    signal: EngagementSignalSpec = Field(default_factory=EngagementSignalSpec)
    model_id: Optional[str] = None
    region: Optional[str] = None
    status: str = "pending"  # pending|processing|completed|failed
    stage: str = ""  # waiting|signal|stats|explain|recommend
    stage_detail: str = ""
    progress_pct: int = 0
    error_message: Optional[str] = None
    duration_sec: float = 0.0
    headline: str = ""
    kpis: dict = Field(default_factory=dict)
    report_gcs_uri: Optional[str] = None
    schema_version: str = ENGAGEMENT_REPORT_VERSION
    usage: UsageMetrics = Field(default_factory=UsageMetrics)
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    invite_code: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    completedAt: Optional[datetime] = None

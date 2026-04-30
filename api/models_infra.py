"""Infrastructure models: uploads, invite codes, AI models registry."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from models_core import generate_id


# ── Uploads ──────────────────────────────────────────────────────────


class CompressedVariant(BaseModel):
    resolution: str  # "480p" | "720p"
    gcs_uri: str = ""
    job_name: str = ""
    status: str = "pending"  # pending | processing | succeeded | failed
    child_upload_id: Optional[str] = None


class UploadRecord(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("up-"))
    filename: str
    display_name: str = ""
    mime_type: str
    file_type: str = "other"  # "video" | "image" | "other"
    gcs_uri: str
    file_size_bytes: int = 0
    status: str = "completed"  # "pending" | "completed" | "failed"
    compressed_variants: List[CompressedVariant] = []
    parent_upload_id: Optional[str] = None
    resolution_label: Optional[str] = None
    signed_urls: dict = Field(default_factory=dict)
    archived: bool = False
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class UploadInitRequest(BaseModel):
    filename: str
    content_type: str
    file_size_bytes: int = 0


class UploadCompleteRequest(BaseModel):
    record_id: str


# ── Invite codes ─────────────────────────────────────────────────────


class InviteCode(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("inv-"))
    code: str
    label: str = ""
    is_active: bool = True
    daily_credits: int = 250
    expires_at: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class CreateInviteCodeRequest(BaseModel):
    code: str
    label: str = ""
    daily_credits: int = 250
    expires_at: Optional[datetime] = None


class ValidateCodeRequest(BaseModel):
    code: str


# ── AI Models registry ───────────────────────────────────────────────


class ModelCapability(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"


AVAILABLE_REGIONS = [
    "global",
    # US
    "us-central1",
    "us-east1",
    "us-east4",
    "us-east5",
    "us-west1",
    "us-west4",
    "us-south1",
    # Americas
    "northamerica-northeast1",
    "southamerica-east1",
    # Europe
    "europe-west1",
    "europe-west2",
    "europe-west3",
    "europe-west4",
    "europe-west6",
    "europe-west8",
    "europe-west9",
    "europe-north1",
    "europe-central2",
    # Asia-Pacific
    "asia-south1",
    "asia-southeast1",
    "asia-east2",
    "asia-northeast1",
    "asia-northeast3",
    "australia-southeast1",
    # Middle East
    "me-west1",
    "me-central1",
    "me-central2",
]


class AIModel(BaseModel):
    id: str = Field(default_factory=lambda: generate_id("mdl-"))
    name: str
    code: str
    provider: str
    capability: ModelCapability
    regions: list = Field(default_factory=lambda: ["global"])
    is_default: bool = False
    is_active: bool = True
    createdAt: datetime = Field(default_factory=datetime.utcnow)


class CreateAIModelRequest(BaseModel):
    name: str
    code: str
    provider: str
    capability: str
    regions: list = Field(default_factory=lambda: ["global"])
    is_default: bool = False

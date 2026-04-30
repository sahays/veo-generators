"""Core Pydantic models: usage metrics, pricing, enums, helpers.

Referenced by every other models_* module. Kept import-only — no runtime
dependencies on other models files to avoid circular imports.
"""

import random
import string
from datetime import datetime
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


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
    """Facts about a job run. Cost fields are denormalized caches — the
    authoritative cost is always computed by `/pricing/usage` from these
    facts against current rates in `pricing_config`."""

    # --- facts (authoritative) ---
    input_tokens: int = 0
    output_tokens: int = 0
    model_name: str = ""
    image_generations: int = 0
    image_input_tokens: int = 0
    image_output_tokens: int = 0
    image_model_name: str = ""
    veo_videos: int = 0
    veo_seconds: int = 0
    veo_model_id: str = ""
    transcoder_minutes: float = 0.0
    transcoder_tier: str = ""  # "sd" | "hd" | "4k"
    diarization_minutes: float = 0.0

    # --- provenance ---
    pricing_confidence: str = "high"  # "high" | "medium" | "low"
    pricing_notes: str = ""

    # --- denormalized cost caches (recomputed from facts each write) ---
    cost_usd: float = 0.0
    image_cost_usd: float = 0.0
    veo_unit_cost: float = 0.0
    veo_cost_usd: float = 0.0
    transcoder_cost_usd: float = 0.0
    diarization_cost_usd: float = 0.0


class ServiceLineItem(BaseModel):
    """One line in a pricing breakdown — one row in the 'Services used' panel."""

    id: str
    label: str
    unit: str  # "token" | "image" | "second" | "minute"
    units: float
    unit_cost_usd: float
    subtotal_usd: float


class FeaturePricing(BaseModel):
    """Pricing info for a single feature — used by /pricing/features + /pricing/usage."""

    feature: str
    services: List[ServiceLineItem]
    total_usd: float
    confidence: Optional[str] = None  # "high" | "medium" | "low" (usage responses only)
    notes: Optional[str] = None


class PricingEstimateRequest(BaseModel):
    """Pre-run estimate request. Feature-specific fields are optional."""

    feature: str
    # Common
    source_duration_seconds: Optional[float] = None
    # Production
    video_length_seconds: Optional[float] = None
    scene_count: Optional[int] = None
    video_model: Optional[str] = None
    text_model: Optional[str] = None
    image_model: Optional[str] = None
    # Adapts
    variant_count: Optional[int] = None
    # Promo
    segment_count: Optional[int] = None
    has_title_card: Optional[bool] = None
    # Thumbnails
    thumbnail_count: Optional[int] = None


class AIResponseWrapper(BaseModel):
    data: Any
    usage: UsageMetrics

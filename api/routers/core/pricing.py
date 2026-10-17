"""Pricing API router: rates catalog, feature->services map, estimator, usage summary.

Business logic lives in `api/pricing_estimator.py` (pre-run) and
`api/pricing_usage.py` (post-run). This module only defines routes.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

import deps
from models import FeaturePricing, PricingEstimateRequest
from pricing_config import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    DEFAULT_TRANSCODER_TIER,
    DEFAULT_VIDEO_MODEL,
    DIARIZATION,
    FEATURE_SERVICES,
    FLAT_SERVICES,
    HINTS,
    IMAGE_MODELS,
    TEXT_MODELS,
    VEO_BY_MODEL,
)
from pricing_estimator import ESTIMATORS
from pricing_usage import USAGE_GETTERS, usage_of, usage_to_line_items

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


def _serialize_text_models() -> dict[str, Any]:
    """Format text model rate tiers for `/pricing/rates`."""
    return {
        m.model_id: {
            "label": m.label,
            "tiers": [
                {
                    "threshold_tokens": t.threshold_tokens,
                    "input_per_token": t.input_per_token,
                    "output_per_token": t.output_per_token,
                }
                for t in m.tiers
            ],
        }
        for m in TEXT_MODELS.values()
    }


@router.get("/rates")
async def get_rates() -> dict[str, Any]:
    """Return full rate catalog across text, image, video, and flat services."""
    image_models = {
        m.model_id: {
            "label": m.label,
            "input_per_token": m.input_per_token,
            "output_per_token": m.output_per_token,
        }
        for m in IMAGE_MODELS.values()
    }
    video_models = {
        mid: {"label": r.label, "per_second": r.unit_cost_usd}
        for mid, r in VEO_BY_MODEL.items()
    }
    flat_services = {
        r.id: {"label": r.label, "unit": r.unit, "unit_cost_usd": r.unit_cost_usd}
        for r in FLAT_SERVICES.values()
    }
    return {
        "text_models": _serialize_text_models(),
        "image_models": image_models,
        "video_models": video_models,
        "flat_services": flat_services,
    }


def _gemini_service_entry(service_key: str) -> dict[str, Any]:
    """Build service entry for `gemini_text` or `gemini_image`."""
    if service_key == "gemini_text":
        tm = TEXT_MODELS[DEFAULT_TEXT_MODEL]
        tier = tm.tiers[0]
        detail = f"input {tier.input_per_token * 1e6:.2f}/1M, output {tier.output_per_token * 1e6:.2f}/1M USD"
        return {
            "id": "gemini_text",
            "label": f"{tm.label} (text)",
            "unit": "token",
            "unit_cost_usd": tier.output_per_token,
            "detail": detail,
        }
    im = IMAGE_MODELS[DEFAULT_IMAGE_MODEL]
    detail = f"output {im.output_per_token * 1e6:.2f}/1M USD (~${im.output_per_token * HINTS.image_output_tokens:.4f}/image)"
    return {
        "id": "gemini_image",
        "label": im.label,
        "unit": "token",
        "unit_cost_usd": im.output_per_token,
        "detail": detail,
    }


def _service_entry(service_key: str) -> dict[str, Any]:
    """Render one service entry for the /pricing/features payload."""
    if service_key in ("gemini_text", "gemini_image"):
        return _gemini_service_entry(service_key)
    if service_key == "veo":
        rate = VEO_BY_MODEL[DEFAULT_VIDEO_MODEL]
        return {
            "id": "veo",
            "label": rate.label,
            "unit": rate.unit,
            "unit_cost_usd": rate.unit_cost_usd,
        }
    if service_key == "transcoder":
        r = DEFAULT_TRANSCODER_TIER
        return {
            "id": r.id,
            "label": r.label,
            "unit": r.unit,
            "unit_cost_usd": r.unit_cost_usd,
        }
    if service_key == "diarization":
        return {
            "id": DIARIZATION.id,
            "label": DIARIZATION.label,
            "unit": DIARIZATION.unit,
            "unit_cost_usd": DIARIZATION.unit_cost_usd,
        }
    return {"id": service_key, "label": service_key, "unit": "", "unit_cost_usd": 0.0}


@router.get("/features")
async def get_features() -> dict[str, Any]:
    """Return mapping of each feature to its billable services."""
    return {
        "features": {
            feature: {"services": [_service_entry(s) for s in service_keys]}
            for feature, service_keys in FEATURE_SERVICES.items()
        }
    }


@router.post("/estimate", response_model=FeaturePricing)
async def estimate(req: PricingEstimateRequest) -> FeaturePricing:
    """Estimate cost breakdown for a feature run before execution."""
    estimator = ESTIMATORS.get(req.feature)
    if not estimator:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {req.feature}")
    items = estimator(req)
    return FeaturePricing(
        feature=req.feature,
        services=items,
        total_usd=sum(i.subtotal_usd for i in items),
    )


@router.get("/usage/{feature}/{record_id}", response_model=FeaturePricing)
async def get_usage(feature: str, record_id: str) -> FeaturePricing:
    """Return actual post-run usage and cost breakdown for a record."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    getter_name = USAGE_GETTERS.get(feature)
    if not getter_name:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")
    record = getattr(deps.firestore_svc, getter_name)(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{feature} {record_id} not found")
    usage = usage_of(record, feature)
    items = usage_to_line_items(usage)
    return FeaturePricing(
        feature=feature,
        services=items,
        total_usd=sum(i.subtotal_usd for i in items),
        confidence=getattr(usage, "pricing_confidence", None) if usage else None,
        notes=getattr(usage, "pricing_notes", None) if usage else None,
    )

"""Pricing API — rate catalog, feature→services map, estimator, usage summary."""

import logging

from fastapi import APIRouter, HTTPException

import deps
from models import (
    FeaturePricing,
    PricingEstimateRequest,
    ServiceLineItem,
)
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
    cost_for_image,
    cost_for_text,
    cost_for_veo,
    veo_rate_for,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pricing", tags=["pricing"])


# ---------------------------------------------------------------------------
# GET /pricing/rates — raw catalog
# ---------------------------------------------------------------------------


@router.get("/rates")
async def get_rates() -> dict:
    return {
        "text_models": {
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
        },
        "image_models": {
            m.model_id: {
                "label": m.label,
                "input_per_token": m.input_per_token,
                "output_per_token": m.output_per_token,
            }
            for m in IMAGE_MODELS.values()
        },
        "video_models": {
            model_id: {"label": rate.label, "per_second": rate.unit_cost_usd}
            for model_id, rate in VEO_BY_MODEL.items()
        },
        "flat_services": {
            r.id: {"label": r.label, "unit": r.unit, "unit_cost_usd": r.unit_cost_usd}
            for r in FLAT_SERVICES.values()
        },
    }


# ---------------------------------------------------------------------------
# GET /pricing/features — feature→services map, rates inlined
# ---------------------------------------------------------------------------


def _service_entry(service_key: str) -> dict:
    """Render one service entry for the features payload."""
    if service_key == "gemini_text":
        m = TEXT_MODELS[DEFAULT_TEXT_MODEL]
        tier = m.tiers[0]
        return {
            "id": "gemini_text",
            "label": f"{m.label} (text)",
            "unit": "token",
            "unit_cost_usd": tier.output_per_token,  # display output rate
            "detail": f"input {tier.input_per_token * 1e6:.2f}/1M, output {tier.output_per_token * 1e6:.2f}/1M USD",
        }
    if service_key == "gemini_image":
        m = IMAGE_MODELS[DEFAULT_IMAGE_MODEL]
        return {
            "id": "gemini_image",
            "label": f"{m.label}",
            "unit": "token",
            "unit_cost_usd": m.output_per_token,
            "detail": f"output {m.output_per_token * 1e6:.2f}/1M USD (~${m.output_per_token * HINTS.image_output_tokens:.4f}/image)",
        }
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
async def get_features() -> dict:
    return {
        "features": {
            feature: {
                "services": [_service_entry(s) for s in service_keys],
            }
            for feature, service_keys in FEATURE_SERVICES.items()
        }
    }


# ---------------------------------------------------------------------------
# POST /pricing/estimate — pre-run estimate
# ---------------------------------------------------------------------------


def _item(
    id: str, label: str, unit: str, units: float, unit_cost: float, subtotal: float
) -> ServiceLineItem:
    return ServiceLineItem(
        id=id,
        label=label,
        unit=unit,
        units=units,
        unit_cost_usd=unit_cost,
        subtotal_usd=subtotal,
    )


def _estimate_production(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    scene_count = req.scene_count or 1
    video_seconds = req.video_length_seconds or (scene_count * 8)
    text_model = req.text_model or DEFAULT_TEXT_MODEL
    image_model = req.image_model or DEFAULT_IMAGE_MODEL
    video_model = req.video_model or DEFAULT_VIDEO_MODEL

    # Gemini text (analyze_brief + per-scene)
    text_in = HINTS.production_analyze_input_tokens
    text_out = HINTS.production_analyze_output_tokens
    text_cost = cost_for_text(text_model, text_in, text_out)
    # Image generation (one per scene)
    img_in = HINTS.image_input_tokens * scene_count
    img_out = HINTS.image_output_tokens * scene_count
    image_cost = cost_for_image(image_model, img_in, img_out)
    # Veo generation
    veo_cost = cost_for_veo(video_model, video_seconds)
    veo_rate = veo_rate_for(video_model)
    # Transcoder HD
    transcoder_minutes = video_seconds / 60.0
    transcoder_cost = transcoder_minutes * DEFAULT_TRANSCODER_TIER.unit_cost_usd

    return [
        _item(
            "gemini_text",
            TEXT_MODELS[text_model].label,
            "token",
            text_in + text_out,
            0.0,
            text_cost,
        ),
        _item(
            "gemini_image",
            IMAGE_MODELS[image_model].label,
            "token",
            img_out,
            IMAGE_MODELS[image_model].output_per_token,
            image_cost,
        ),
        _item(
            "veo",
            veo_rate.label,
            "second",
            video_seconds,
            veo_rate.unit_cost_usd,
            veo_cost,
        ),
        _item(
            "transcoder_hd",
            DEFAULT_TRANSCODER_TIER.label,
            "minute",
            transcoder_minutes,
            DEFAULT_TRANSCODER_TIER.unit_cost_usd,
            transcoder_cost,
        ),
    ]


def _estimate_adapts(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    n = req.variant_count or 1
    image_model = req.image_model or DEFAULT_IMAGE_MODEL
    img_in = HINTS.image_input_tokens * n
    img_out = HINTS.image_output_tokens * n
    cost = cost_for_image(image_model, img_in, img_out)
    return [
        _item(
            "gemini_image",
            IMAGE_MODELS[image_model].label,
            "token",
            img_out,
            IMAGE_MODELS[image_model].output_per_token,
            cost,
        ),
    ]


def _estimate_reframe(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    duration = req.source_duration_seconds or 60
    text_model = req.text_model or DEFAULT_TEXT_MODEL
    text_cost = cost_for_text(
        text_model,
        HINTS.reframe_analyze_input_tokens,
        HINTS.reframe_analyze_output_tokens,
    )
    diar_min = duration / 60.0
    diar_cost = diar_min * DIARIZATION.unit_cost_usd
    trans_min = duration / 60.0
    trans_cost = trans_min * DEFAULT_TRANSCODER_TIER.unit_cost_usd
    return [
        _item(
            "gemini_text",
            TEXT_MODELS[text_model].label,
            "token",
            HINTS.reframe_analyze_input_tokens + HINTS.reframe_analyze_output_tokens,
            0.0,
            text_cost,
        ),
        _item(
            "diarization",
            DIARIZATION.label,
            "minute",
            diar_min,
            DIARIZATION.unit_cost_usd,
            diar_cost,
        ),
        _item(
            "transcoder_hd",
            DEFAULT_TRANSCODER_TIER.label,
            "minute",
            trans_min,
            DEFAULT_TRANSCODER_TIER.unit_cost_usd,
            trans_cost,
        ),
    ]


def _estimate_promo(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    segments = req.segment_count or 3
    text_model = req.text_model or DEFAULT_TEXT_MODEL
    image_model = req.image_model or DEFAULT_IMAGE_MODEL
    text_cost = cost_for_text(
        text_model,
        HINTS.promo_segment_input_tokens,
        HINTS.promo_segment_output_tokens,
    )
    # 1 overlay per segment + optional title card
    images = segments + (1 if req.has_title_card else 0)
    img_in = HINTS.image_input_tokens * images
    img_out = HINTS.image_output_tokens * images
    image_cost = cost_for_image(image_model, img_in, img_out)
    return [
        _item(
            "gemini_text",
            TEXT_MODELS[text_model].label,
            "token",
            HINTS.promo_segment_input_tokens + HINTS.promo_segment_output_tokens,
            0.0,
            text_cost,
        ),
        _item(
            "gemini_image",
            IMAGE_MODELS[image_model].label,
            "token",
            img_out,
            IMAGE_MODELS[image_model].output_per_token,
            image_cost,
        ),
    ]


def _estimate_key_moments(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    text_model = req.text_model or DEFAULT_TEXT_MODEL
    text_cost = cost_for_text(
        text_model,
        HINTS.key_moments_input_tokens,
        HINTS.key_moments_output_tokens,
    )
    return [
        _item(
            "gemini_text",
            TEXT_MODELS[text_model].label,
            "token",
            HINTS.key_moments_input_tokens + HINTS.key_moments_output_tokens,
            0.0,
            text_cost,
        ),
    ]


def _estimate_thumbnails(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    n = req.thumbnail_count or 1
    text_model = req.text_model or DEFAULT_TEXT_MODEL
    image_model = req.image_model or DEFAULT_IMAGE_MODEL
    text_cost = cost_for_text(
        text_model,
        HINTS.thumbnails_analyze_input_tokens,
        HINTS.thumbnails_analyze_output_tokens,
    )
    img_in = HINTS.image_input_tokens * n
    img_out = HINTS.image_output_tokens * n
    image_cost = cost_for_image(image_model, img_in, img_out)
    return [
        _item(
            "gemini_text",
            TEXT_MODELS[text_model].label,
            "token",
            HINTS.thumbnails_analyze_input_tokens
            + HINTS.thumbnails_analyze_output_tokens,
            0.0,
            text_cost,
        ),
        _item(
            "gemini_image",
            IMAGE_MODELS[image_model].label,
            "token",
            img_out,
            IMAGE_MODELS[image_model].output_per_token,
            image_cost,
        ),
    ]


_ESTIMATORS = {
    "production": _estimate_production,
    "adapts": _estimate_adapts,
    "reframe": _estimate_reframe,
    "promo": _estimate_promo,
    "key_moments": _estimate_key_moments,
    "thumbnails": _estimate_thumbnails,
}


@router.post("/estimate", response_model=FeaturePricing)
async def estimate(req: PricingEstimateRequest) -> FeaturePricing:
    estimator = _ESTIMATORS.get(req.feature)
    if not estimator:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {req.feature}")
    items = estimator(req)
    total = sum(i.subtotal_usd for i in items)
    return FeaturePricing(feature=req.feature, services=items, total_usd=total)


# ---------------------------------------------------------------------------
# GET /pricing/usage/{feature}/{record_id} — actual usage, normalized
# ---------------------------------------------------------------------------


_USAGE_GETTERS = {
    "production": "get_production",
    "adapts": "get_adapt_record",
    "reframe": "get_reframe_record",
    "promo": "get_promo_record",
    "key_moments": "get_key_moments_analysis",
    "thumbnails": "get_thumbnail_record",
}

_USAGE_FIELD = {
    "production": "total_usage",
}


def _usage_of(record, feature: str):
    field = _USAGE_FIELD.get(feature, "usage")
    return getattr(record, field, None)


def _usage_to_line_items(usage, feature: str) -> list[ServiceLineItem]:
    """Convert a record's UsageMetrics into per-service line items.

    Always recomputes cost from current rates in pricing_config, using stored
    model IDs where available (veo_model_id, image_model_name, transcoder_tier).
    Stored *_cost_usd caches are intentionally ignored so rate changes
    retroactively re-price every record.
    """
    from pricing_config import FLAT_SERVICES

    items: list[ServiceLineItem] = []
    if not usage:
        return items

    # Gemini text — compute from model + token counts
    if usage.input_tokens or usage.output_tokens:
        text_model_id = usage.model_name or DEFAULT_TEXT_MODEL
        text_model = TEXT_MODELS.get(text_model_id)
        label = text_model.label if text_model else (text_model_id or "Gemini text")
        text_cost = cost_for_text(
            text_model_id, usage.input_tokens, usage.output_tokens
        )
        items.append(
            ServiceLineItem(
                id="gemini_text",
                label=f"{label} (text)",
                unit="token",
                units=usage.input_tokens + usage.output_tokens,
                unit_cost_usd=0.0,
                subtotal_usd=text_cost,
            )
        )

    # Gemini image — compute from image_model_name (fallback default) × stored tokens
    if usage.image_generations:
        img_model_id = usage.image_model_name or DEFAULT_IMAGE_MODEL
        img_model = IMAGE_MODELS.get(img_model_id) or IMAGE_MODELS[DEFAULT_IMAGE_MODEL]
        out_tokens = usage.image_output_tokens or (
            usage.image_generations * HINTS.image_output_tokens
        )
        in_tokens = usage.image_input_tokens or (
            usage.image_generations * HINTS.image_input_tokens
        )
        img_cost = cost_for_image(img_model.model_id, in_tokens, out_tokens)
        items.append(
            ServiceLineItem(
                id="gemini_image",
                label=f"{img_model.label} ({usage.image_generations} images)",
                unit="token",
                units=out_tokens,
                unit_cost_usd=img_model.output_per_token,
                subtotal_usd=img_cost,
            )
        )

    # Veo — resolve rate from veo_model_id; fall back to matching stored unit_cost
    if usage.veo_videos:
        veo_rate = VEO_BY_MODEL.get(usage.veo_model_id) if usage.veo_model_id else None
        if not veo_rate and usage.veo_unit_cost:
            for r in VEO_BY_MODEL.values():
                if abs(r.unit_cost_usd - usage.veo_unit_cost) < 1e-9:
                    veo_rate = r
                    break
        if not veo_rate:
            veo_rate = VEO_BY_MODEL[DEFAULT_VIDEO_MODEL]
        veo_cost = usage.veo_seconds * veo_rate.unit_cost_usd
        items.append(
            ServiceLineItem(
                id="veo",
                label=f"{veo_rate.label} ({usage.veo_videos} videos)",
                unit="second",
                units=usage.veo_seconds,
                unit_cost_usd=veo_rate.unit_cost_usd,
                subtotal_usd=veo_cost,
            )
        )

    # Transcoder — resolve tier from stored transcoder_tier (fallback HD)
    if usage.transcoder_minutes:
        tier_key = (
            f"transcoder_{usage.transcoder_tier}"
            if usage.transcoder_tier
            else DEFAULT_TRANSCODER_TIER.id
        )
        tier = FLAT_SERVICES.get(tier_key, DEFAULT_TRANSCODER_TIER)
        tr_cost = usage.transcoder_minutes * tier.unit_cost_usd
        items.append(
            ServiceLineItem(
                id=tier.id,
                label=tier.label,
                unit="minute",
                units=usage.transcoder_minutes,
                unit_cost_usd=tier.unit_cost_usd,
                subtotal_usd=tr_cost,
            )
        )

    # Diarization
    if usage.diarization_minutes:
        diar_cost = usage.diarization_minutes * DIARIZATION.unit_cost_usd
        items.append(
            ServiceLineItem(
                id=DIARIZATION.id,
                label=DIARIZATION.label,
                unit="minute",
                units=usage.diarization_minutes,
                unit_cost_usd=DIARIZATION.unit_cost_usd,
                subtotal_usd=diar_cost,
            )
        )

    return items


@router.get("/usage/{feature}/{record_id}", response_model=FeaturePricing)
async def get_usage(feature: str, record_id: str) -> FeaturePricing:
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    getter_name = _USAGE_GETTERS.get(feature)
    if not getter_name:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")
    getter = getattr(deps.firestore_svc, getter_name)
    record = getter(record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"{feature} {record_id} not found")
    usage = _usage_of(record, feature)
    items = _usage_to_line_items(usage, feature)
    total = sum(i.subtotal_usd for i in items)
    return FeaturePricing(
        feature=feature,
        services=items,
        total_usd=total,
        confidence=getattr(usage, "pricing_confidence", None) if usage else None,
        notes=getattr(usage, "pricing_notes", None) if usage else None,
    )

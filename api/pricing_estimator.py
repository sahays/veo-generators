"""Pre-run cost estimator. Returns per-service line items for any feature.

Used by `POST /api/v1/pricing/estimate`. Rates are resolved from
`pricing_config` at call time, so rate changes take effect without redeploy.
"""

from models import PricingEstimateRequest, ServiceLineItem
from pricing_config import (
    DEFAULT_IMAGE_MODEL,
    DEFAULT_TEXT_MODEL,
    DEFAULT_TRANSCODER_TIER,
    DEFAULT_VIDEO_MODEL,
    DIARIZATION,
    FLAT_SERVICES,
    HINTS,
    IMAGE_MODELS,
    TEXT_MODELS,
    cost_for_image,
    cost_for_text,
    cost_for_veo,
    veo_rate_for,
)


# ── Per-service line-item builders ────────────────────────────────────


def _text_item(model_id: str, in_tok: int, out_tok: int) -> ServiceLineItem:
    model = TEXT_MODELS[model_id]
    return ServiceLineItem(
        id="gemini_text",
        label=model.label,
        unit="token",
        units=in_tok + out_tok,
        unit_cost_usd=0.0,
        subtotal_usd=cost_for_text(model_id, in_tok, out_tok),
    )


def _image_item(model_id: str, count: int) -> ServiceLineItem:
    model = IMAGE_MODELS[model_id]
    in_tok = HINTS.image_input_tokens * count
    out_tok = HINTS.image_output_tokens * count
    return ServiceLineItem(
        id="gemini_image",
        label=model.label,
        unit="token",
        units=out_tok,
        unit_cost_usd=model.output_per_token,
        subtotal_usd=cost_for_image(model_id, in_tok, out_tok),
    )


def _veo_item(model_id: str, seconds: float) -> ServiceLineItem:
    rate = veo_rate_for(model_id)
    return ServiceLineItem(
        id="veo",
        label=rate.label,
        unit="second",
        units=seconds,
        unit_cost_usd=rate.unit_cost_usd,
        subtotal_usd=cost_for_veo(model_id, seconds),
    )


def _flat_item(service_id: str, minutes: float) -> ServiceLineItem:
    rate = FLAT_SERVICES[service_id]
    return ServiceLineItem(
        id=rate.id,
        label=rate.label,
        unit=rate.unit,
        units=minutes,
        unit_cost_usd=rate.unit_cost_usd,
        subtotal_usd=minutes * rate.unit_cost_usd,
    )


# ── Per-feature estimators ───────────────────────────────────────────


def _estimate_production(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    scenes = req.scene_count or 1
    seconds = req.video_length_seconds or (scenes * 8)
    return [
        _text_item(
            req.text_model or DEFAULT_TEXT_MODEL,
            HINTS.production_analyze_input_tokens,
            HINTS.production_analyze_output_tokens,
        ),
        _image_item(req.image_model or DEFAULT_IMAGE_MODEL, scenes),
        _veo_item(req.video_model or DEFAULT_VIDEO_MODEL, seconds),
        _flat_item(DEFAULT_TRANSCODER_TIER.id, seconds / 60.0),
    ]


def _estimate_adapts(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    return [_image_item(req.image_model or DEFAULT_IMAGE_MODEL, req.variant_count or 1)]


def _estimate_reframe(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    minutes = (req.source_duration_seconds or 60) / 60.0
    return [
        _text_item(
            req.text_model or DEFAULT_TEXT_MODEL,
            HINTS.reframe_analyze_input_tokens,
            HINTS.reframe_analyze_output_tokens,
        ),
        _flat_item(DIARIZATION.id, minutes),
        _flat_item(DEFAULT_TRANSCODER_TIER.id, minutes),
    ]


def _estimate_promo(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    images = (req.segment_count or 3) + (1 if req.has_title_card else 0)
    return [
        _text_item(
            req.text_model or DEFAULT_TEXT_MODEL,
            HINTS.promo_segment_input_tokens,
            HINTS.promo_segment_output_tokens,
        ),
        _image_item(req.image_model or DEFAULT_IMAGE_MODEL, images),
    ]


def _estimate_key_moments(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    return [
        _text_item(
            req.text_model or DEFAULT_TEXT_MODEL,
            HINTS.key_moments_input_tokens,
            HINTS.key_moments_output_tokens,
        ),
    ]


def _estimate_thumbnails(req: PricingEstimateRequest) -> list[ServiceLineItem]:
    return [
        _text_item(
            req.text_model or DEFAULT_TEXT_MODEL,
            HINTS.thumbnails_analyze_input_tokens,
            HINTS.thumbnails_analyze_output_tokens,
        ),
        _image_item(req.image_model or DEFAULT_IMAGE_MODEL, req.thumbnail_count or 1),
    ]


ESTIMATORS = {
    "production": _estimate_production,
    "adapts": _estimate_adapts,
    "reframe": _estimate_reframe,
    "promo": _estimate_promo,
    "key_moments": _estimate_key_moments,
    "thumbnails": _estimate_thumbnails,
}

"""Actual-usage pricing: converts a record's `UsageMetrics` into per-service
line items using current rates. Used by `GET /api/v1/pricing/usage/...`.

Stored `*_cost_usd` caches are intentionally ignored — the authoritative cost
is always computed here from facts against the live `pricing_config` rates.
"""

from models import ServiceLineItem
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
    VEO_BY_MODEL,
    cost_for_image,
    cost_for_text,
)


USAGE_GETTERS = {
    "production": "get_production",
    "adapts": "get_adapt_record",
    "reframe": "get_reframe_record",
    "promo": "get_promo_record",
    "key_moments": "get_key_moments_analysis",
    "thumbnails": "get_thumbnail_record",
}

# Most features store usage in `.usage`; productions use `.total_usage`.
_USAGE_FIELD = {"production": "total_usage"}


def usage_of(record, feature: str):
    return getattr(record, _USAGE_FIELD.get(feature, "usage"), None)


def _text_line_item(usage) -> ServiceLineItem:
    model_id = usage.model_name or DEFAULT_TEXT_MODEL
    model = TEXT_MODELS.get(model_id)
    label = model.label if model else (model_id or "Gemini text")
    return ServiceLineItem(
        id="gemini_text",
        label=f"{label} (text)",
        unit="token",
        units=usage.input_tokens + usage.output_tokens,
        unit_cost_usd=0.0,
        subtotal_usd=cost_for_text(model_id, usage.input_tokens, usage.output_tokens),
    )


def _image_line_item(usage) -> ServiceLineItem:
    model_id = usage.image_model_name or DEFAULT_IMAGE_MODEL
    model = IMAGE_MODELS.get(model_id) or IMAGE_MODELS[DEFAULT_IMAGE_MODEL]
    out_tokens = usage.image_output_tokens or (
        usage.image_generations * HINTS.image_output_tokens
    )
    in_tokens = usage.image_input_tokens or (
        usage.image_generations * HINTS.image_input_tokens
    )
    return ServiceLineItem(
        id="gemini_image",
        label=f"{model.label} ({usage.image_generations} images)",
        unit="token",
        units=out_tokens,
        unit_cost_usd=model.output_per_token,
        subtotal_usd=cost_for_image(model.model_id, in_tokens, out_tokens),
    )


def _resolve_veo_rate(usage):
    """Resolve the Veo rate from stored model_id or legacy unit_cost."""
    if usage.veo_model_id:
        rate = VEO_BY_MODEL.get(usage.veo_model_id)
        if rate:
            return rate
    if usage.veo_unit_cost:
        for r in VEO_BY_MODEL.values():
            if abs(r.unit_cost_usd - usage.veo_unit_cost) < 1e-9:
                return r
    return VEO_BY_MODEL[DEFAULT_VIDEO_MODEL]


def _veo_line_item(usage) -> ServiceLineItem:
    rate = _resolve_veo_rate(usage)
    return ServiceLineItem(
        id="veo",
        label=f"{rate.label} ({usage.veo_videos} videos)",
        unit="second",
        units=usage.veo_seconds,
        unit_cost_usd=rate.unit_cost_usd,
        subtotal_usd=usage.veo_seconds * rate.unit_cost_usd,
    )


def _transcoder_line_item(usage) -> ServiceLineItem:
    tier_key = (
        f"transcoder_{usage.transcoder_tier}"
        if usage.transcoder_tier
        else DEFAULT_TRANSCODER_TIER.id
    )
    tier = FLAT_SERVICES.get(tier_key, DEFAULT_TRANSCODER_TIER)
    return ServiceLineItem(
        id=tier.id,
        label=tier.label,
        unit="minute",
        units=usage.transcoder_minutes,
        unit_cost_usd=tier.unit_cost_usd,
        subtotal_usd=usage.transcoder_minutes * tier.unit_cost_usd,
    )


def _diarization_line_item(usage) -> ServiceLineItem:
    return ServiceLineItem(
        id=DIARIZATION.id,
        label=DIARIZATION.label,
        unit="minute",
        units=usage.diarization_minutes,
        unit_cost_usd=DIARIZATION.unit_cost_usd,
        subtotal_usd=usage.diarization_minutes * DIARIZATION.unit_cost_usd,
    )


def usage_to_line_items(usage) -> list[ServiceLineItem]:
    """Convert a record's UsageMetrics into per-service line items at live rates."""
    items: list[ServiceLineItem] = []
    if not usage:
        return items
    if usage.input_tokens or usage.output_tokens:
        items.append(_text_line_item(usage))
    if usage.image_generations:
        items.append(_image_line_item(usage))
    if usage.veo_videos:
        items.append(_veo_line_item(usage))
    if usage.transcoder_minutes:
        items.append(_transcoder_line_item(usage))
    if usage.diarization_minutes:
        items.append(_diarization_line_item(usage))
    return items

"""Cost accumulation utilities.

Generalized across productions, adapts, reframes, promos, key_moments,
thumbnails. Reads rates from `pricing_config` so there is a single source
of truth. The legacy `accumulate_image_cost` / `accumulate_veo_cost` helpers
(production-only) are preserved for backwards compatibility.
"""

from typing import Callable, Optional

import deps
from pricing_config import (
    DEFAULT_TRANSCODER_TIER,
    DIARIZATION,
    FlatRate,
    veo_rate_for,
)

# Feature → (getter, updater) on firestore_svc. The getter must return a
# record with `.total_usage` (productions) or `.usage` (everything else).
_FEATURE_DISPATCH: dict[str, tuple[str, str, str]] = {
    # feature_id : (getter_method, updater_method, usage_field)
    "production": ("get_production", "update_production", "total_usage"),
    "adapts": ("get_adapt_record", "update_adapt_record", "usage"),
    "reframe": ("get_reframe_record", "update_reframe_record", "usage"),
    "promo": ("get_promo_record", "update_promo_record", "usage"),
    "key_moments": (
        "get_key_moments_analysis",
        "update_key_moments_analysis",
        "usage",
    ),
    "thumbnails": ("get_thumbnail_record", "update_thumbnail_record", "usage"),
}


def _resolve_feature(feature: str) -> tuple[Callable, Callable, str]:
    if feature not in _FEATURE_DISPATCH:
        raise ValueError(f"Unknown feature for cost tracking: {feature}")
    getter_name, updater_name, usage_field = _FEATURE_DISPATCH[feature]
    fs = deps.firestore_svc
    getter = getattr(fs, getter_name)
    updater = getattr(fs, updater_name) if updater_name else None
    return getter, updater, usage_field


def _accumulate(feature: str, record_id: str, field_deltas: dict) -> None:
    """Apply a dict of {field: delta} increments onto a record's usage field.

    Silently no-ops if the record is missing or if the feature has no updater.
    """
    getter, updater, usage_field = _resolve_feature(feature)
    if not updater:
        return
    record = getter(record_id)
    if not record:
        return
    usage = getattr(record, usage_field, None)
    updates = {}
    for key, delta in field_deltas.items():
        current = getattr(usage, key, 0) if usage else 0
        if key == "veo_unit_cost":
            # Not a cumulative field — replace, don't add.
            updates[f"{usage_field}.{key}"] = delta
        else:
            updates[f"{usage_field}.{key}"] = (current or 0) + delta
    updater(record_id, updates)


# ---------------------------------------------------------------------------
# Legacy API (production-only) — preserved for existing call sites.
# ---------------------------------------------------------------------------


def accumulate_cost(production_id: str, cost_usd: float) -> None:
    """Add cost to the production's total_usage."""
    _accumulate("production", production_id, {"cost_usd": cost_usd})


def accumulate_image_cost(production_id: str, cost_per_image: float) -> None:
    """Track image generation cost breakdown on a production's total_usage."""
    _accumulate(
        "production",
        production_id,
        {
            "cost_usd": cost_per_image,
            "image_generations": 1,
            "image_cost_usd": cost_per_image,
        },
    )


def accumulate_veo_cost(
    production_id: str, duration_seconds: int, unit_cost: float
) -> None:
    """Track Veo video generation cost breakdown on a production's total_usage."""
    veo_cost = duration_seconds * unit_cost
    _accumulate(
        "production",
        production_id,
        {
            "cost_usd": veo_cost,
            "veo_videos": 1,
            "veo_seconds": duration_seconds,
            "veo_unit_cost": unit_cost,
            "veo_cost_usd": veo_cost,
        },
    )


# ---------------------------------------------------------------------------
# Generalized API — use for adapts/reframe/promo/thumbnails.
# ---------------------------------------------------------------------------


def accumulate_image_cost_on(
    feature: str,
    record_id: str,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_name: str = "",
) -> None:
    """Accumulate token-based image cost on any feature's record.

    Writes the fact (image_generations + token counts + image_model_name) and
    a denormalized cost_usd cache using current rates.
    """
    _accumulate(
        feature,
        record_id,
        {
            "cost_usd": cost_usd,
            "image_generations": 1,
            "image_input_tokens": input_tokens,
            "image_output_tokens": output_tokens,
            "image_cost_usd": cost_usd,
        },
    )
    if model_name:
        _, updater, usage_field = _resolve_feature(feature)
        if updater:
            updater(record_id, {f"{usage_field}.image_model_name": model_name})


def accumulate_text_cost_on(
    feature: str,
    record_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
    model_name: Optional[str] = None,
) -> None:
    """Accumulate Gemini text cost on any feature's record."""
    deltas = {
        "cost_usd": cost_usd,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    _accumulate(feature, record_id, deltas)
    # Overwrite model_name (last-wins) if provided.
    if model_name:
        _, updater, usage_field = _resolve_feature(feature)
        if updater:
            updater(record_id, {f"{usage_field}.model_name": model_name})


def accumulate_veo_cost_on(
    feature: str, record_id: str, duration_seconds: float, model_id: str
) -> None:
    """Accumulate Veo cost on any feature's record, resolving rate by model.

    Stores `veo_model_id` as the authoritative fact; `veo_unit_cost` and
    `veo_cost_usd` are denormalized caches computed from current rates.
    """
    rate = veo_rate_for(model_id)
    veo_cost = duration_seconds * rate.unit_cost_usd
    _accumulate(
        feature,
        record_id,
        {
            "cost_usd": veo_cost,
            "veo_videos": 1,
            "veo_seconds": duration_seconds,
            "veo_unit_cost": rate.unit_cost_usd,
            "veo_cost_usd": veo_cost,
        },
    )
    _, updater, usage_field = _resolve_feature(feature)
    if updater and model_id:
        updater(record_id, {f"{usage_field}.veo_model_id": model_id})


def accumulate_transcoder_cost(
    feature: str,
    record_id: str,
    minutes: float,
    tier: FlatRate = DEFAULT_TRANSCODER_TIER,
) -> None:
    """Accumulate Cloud Transcoder cost. Default tier is HD 1080p.

    Stores `transcoder_tier` as the authoritative fact (e.g., "hd"); cost is
    a denormalized cache.
    """
    cost = minutes * tier.unit_cost_usd
    _accumulate(
        feature,
        record_id,
        {
            "cost_usd": cost,
            "transcoder_minutes": minutes,
            "transcoder_cost_usd": cost,
        },
    )
    # Derive tier id from the FlatRate.id (e.g., "transcoder_hd" → "hd").
    tier_id = tier.id.replace("transcoder_", "")
    _, updater, usage_field = _resolve_feature(feature)
    if updater:
        updater(record_id, {f"{usage_field}.transcoder_tier": tier_id})


def accumulate_diarization_cost(feature: str, record_id: str, minutes: float) -> None:
    """Accumulate Speech V2 (Chirp 3) diarization cost."""
    cost = minutes * DIARIZATION.unit_cost_usd
    _accumulate(
        feature,
        record_id,
        {
            "cost_usd": cost,
            "diarization_minutes": minutes,
            "diarization_cost_usd": cost,
        },
    )

"""Cost accumulation utilities.

Uses Firestore `Increment` for atomic, race-free updates against the record's
usage field. `/api/v1/pricing/usage` always recomputes cost from facts against
current rates, so the `cost_usd` fields here are a denormalized cache used
only for list/sort views.
"""

from typing import Callable, Optional

from google.cloud import firestore

import deps
from pricing_config import (
    DEFAULT_TRANSCODER_TIER,
    DIARIZATION,
    FlatRate,
    veo_rate_for,
)

# Feature → (getter method, updater method, usage field) on FirestoreService.
_FEATURE_DISPATCH: dict[str, tuple[str, str, str]] = {
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


def _resolve(feature: str) -> tuple[Optional[Callable], Optional[Callable], str]:
    if feature not in _FEATURE_DISPATCH:
        raise ValueError(f"Unknown feature for cost tracking: {feature}")
    getter_name, updater_name, usage_field = _FEATURE_DISPATCH[feature]
    fs = deps.firestore_svc
    if not fs:
        return None, None, usage_field
    return (
        getattr(fs, getter_name, None),
        getattr(fs, updater_name, None),
        usage_field,
    )


def _atomic_update(
    feature: str,
    record_id: str,
    increments: dict,
    sets: Optional[dict] = None,
) -> None:
    """Apply atomic field increments (and optional non-increment sets) in one write.

    `increments` maps field names → numeric deltas; `sets` maps field names →
    replacement values. All paths are prefixed with the feature's usage field.
    """
    _, updater, usage_field = _resolve(feature)
    if not updater:
        return
    updates: dict = {
        f"{usage_field}.{key}": firestore.Increment(delta)
        for key, delta in increments.items()
    }
    if sets:
        for key, value in sets.items():
            updates[f"{usage_field}.{key}"] = value
    updater(record_id, updates)


# ── Per-service accumulators ─────────────────────────────────────────


def accumulate_image_cost_on(
    feature: str,
    record_id: str,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_name: str = "",
) -> None:
    """Atomically add one image generation to the record's usage facts."""
    _atomic_update(
        feature,
        record_id,
        increments={
            "cost_usd": cost_usd,
            "image_generations": 1,
            "image_input_tokens": input_tokens,
            "image_output_tokens": output_tokens,
            "image_cost_usd": cost_usd,
        },
        sets={"image_model_name": model_name} if model_name else None,
    )


def accumulate_text_cost_on(
    feature: str,
    record_id: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
    model_name: Optional[str] = None,
) -> None:
    """Atomically add Gemini text usage to a record."""
    _atomic_update(
        feature,
        record_id,
        increments={
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        sets={"model_name": model_name} if model_name else None,
    )


def accumulate_veo_cost_on(
    feature: str, record_id: str, duration_seconds: float, model_id: str
) -> None:
    """Atomically add one Veo video to a record, resolving rate by model."""
    rate = veo_rate_for(model_id)
    veo_cost = duration_seconds * rate.unit_cost_usd
    _atomic_update(
        feature,
        record_id,
        increments={
            "cost_usd": veo_cost,
            "veo_videos": 1,
            "veo_seconds": duration_seconds,
            "veo_cost_usd": veo_cost,
        },
        sets={
            "veo_unit_cost": rate.unit_cost_usd,
            "veo_model_id": model_id or "",
        },
    )


def accumulate_transcoder_cost(
    feature: str,
    record_id: str,
    minutes: float,
    tier: FlatRate = DEFAULT_TRANSCODER_TIER,
) -> None:
    """Atomically add Cloud Transcoder minutes to a record. Default tier is HD."""
    cost = minutes * tier.unit_cost_usd
    tier_id = tier.id.replace("transcoder_", "")
    _atomic_update(
        feature,
        record_id,
        increments={
            "cost_usd": cost,
            "transcoder_minutes": minutes,
            "transcoder_cost_usd": cost,
        },
        sets={"transcoder_tier": tier_id},
    )


def accumulate_diarization_cost(feature: str, record_id: str, minutes: float) -> None:
    """Atomically add Speech V2 (Chirp 3) diarization minutes to a record."""
    cost = minutes * DIARIZATION.unit_cost_usd
    _atomic_update(
        feature,
        record_id,
        increments={
            "cost_usd": cost,
            "diarization_minutes": minutes,
            "diarization_cost_usd": cost,
        },
    )

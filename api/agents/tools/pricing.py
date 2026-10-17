"""Pricing tools — rates catalog, feature/service map, cost estimates and lookups."""

from ._client import api_call
from .jobs import normalize_feature


async def get_pricing_rates(invite_code: str) -> dict:
    """Get the catalog of current per-service pricing (text models, image models,
    Veo tiers, Cloud Transcoder, Speech V2 diarization)."""
    return await api_call("GET", "/api/v1/pricing/rates", invite_code)


async def get_feature_services(invite_code: str) -> dict:
    """Get the map of features (production, adapts, reframe, promo, key_moments,
    thumbnails) to the services each one consumes, with rates inlined."""
    return await api_call("GET", "/api/v1/pricing/features", invite_code)


async def estimate_cost(invite_code: str, payload: dict) -> dict:
    """Estimate the cost of a job before it runs. Payload must include
    `feature` (one of production/adapts/reframe/promo/key_moments/thumbnails)
    plus feature-specific inputs (scene_count, variant_count,
    source_duration_seconds, segment_count, thumbnail_count, etc.)."""
    norm_payload = dict(payload)
    if "feature" in norm_payload:
        norm_payload["feature"] = normalize_feature(str(norm_payload["feature"]))
    return await api_call(
        "POST", "/api/v1/pricing/estimate", invite_code, json=norm_payload
    )


async def get_job_cost(invite_code: str, feature: str, record_id: str) -> dict:
    """Get the per-service cost and token usage breakdown for a completed (or in-progress) job.
    Returns line items (including token counts in `units`), total cost, and pricing_confidence."""
    norm_feature = normalize_feature(feature)
    return await api_call(
        "GET", f"/api/v1/pricing/usage/{norm_feature}/{record_id}", invite_code
    )

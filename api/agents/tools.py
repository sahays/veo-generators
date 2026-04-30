import logging
from typing import List, Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "http://internal"
_TIMEOUT = 30.0

# Constant lookup — avoids rebuilding on every get_job_status call.
_JOB_ENDPOINT_PREFIXES = {
    "production": "/api/v1/productions",
    "promo": "/api/v1/promo",
    "reframe": "/api/v1/reframe",
    "key_moments": "/api/v1/key-moments",
    "thumbnails": "/api/v1/thumbnails",
    "adapts": "/api/v1/adapts",
}

# Module-level singleton — one AsyncClient + ASGITransport shared across all
# tool invocations. Closing is handled by the FastAPI shutdown hook in main.py.
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # Lazy import to break circular dep (tools → main → routers → agents → tools).
        from main import app

        _client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
            timeout=_TIMEOUT,
        )
    return _client


async def close_client() -> None:
    """Close the shared AsyncClient. Called from FastAPI shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _api_call(
    method: str,
    path: str,
    invite_code: str,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Make an authenticated API call through the FastAPI app."""
    headers = {"X-Invite-Code": invite_code, "User-Agent": "VeoAgent/1.0"}
    client = _get_client()
    response = await client.request(
        method, path, headers=headers, json=json, params=params, follow_redirects=True
    )
    if response.status_code >= 400:
        logger.error(
            "API Error %s on %s: %s", response.status_code, path, response.text
        )
        detail = response.text
        try:
            detail = response.json()
        except Exception:
            pass
        return {"error": f"API returned {response.status_code}", "detail": detail}
    try:
        return response.json()
    except Exception:
        return {"error": "Non-JSON response", "detail": response.text}


# ── Generic helpers to reduce repetition ─────────────────────────────


async def _list_recent(endpoint: str, invite_code: str, limit: int = 5) -> List[dict]:
    """Fetch all records from endpoint and return the most recent `limit` items."""
    result = await _api_call("GET", endpoint, invite_code)
    if isinstance(result, list):
        return result[:limit]
    return []


async def _create_job(endpoint: str, invite_code: str, payload: dict) -> dict:
    return await _api_call("POST", endpoint, invite_code, json=payload)


# ── Public tool functions ────────────────────────────────────────────


async def list_recent_productions(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video production projects."""
    return await _list_recent("/api/v1/productions", invite_code, limit)


async def create_production(
    invite_code: str, name: str, base_concept: str, prompt_id: Optional[str] = None
) -> dict:
    """Create a new video production project."""
    payload: dict = {"name": name, "base_concept": base_concept}
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return await _create_job("/api/v1/productions", invite_code, payload)


async def list_recent_promos(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent promotional video jobs."""
    return await _list_recent("/api/v1/promo", invite_code, limit)


async def create_promo(
    invite_code: str,
    gcs_uri: str,
    target_duration: int = 60,
    source_filename: str = "",
    text_overlay: bool = False,
) -> dict:
    """Trigger a new promotional video generation job."""
    return await _create_job(
        "/api/v1/promo",
        invite_code,
        {
            "gcs_uri": gcs_uri,
            "source_filename": source_filename,
            "target_duration": target_duration,
            "text_overlay": text_overlay,
        },
    )


async def list_uploaded_videos(invite_code: str) -> List[dict]:
    """List all videos that have been uploaded and are ready for processing."""
    return await _api_call("GET", "/api/v1/promo/sources/uploads", invite_code)


async def get_job_status(invite_code: str, job_type: str, job_id: str) -> dict:
    """Check the status of a specific job."""
    prefix = _JOB_ENDPOINT_PREFIXES.get(job_type)
    if not prefix:
        return {"error": f"Unknown job type: {job_type}"}
    return await _api_call("GET", f"{prefix}/{job_id}", invite_code)


async def create_key_moments_analysis(
    invite_code: str, gcs_uri: str, prompt_id: str
) -> dict:
    """Trigger a Key Moments analysis for a video."""
    return await _create_job(
        "/api/v1/key-moments/analyze",
        invite_code,
        {
            "gcs_uri": gcs_uri,
            "prompt_id": prompt_id,
        },
    )


async def create_reframe(
    invite_code: str, gcs_uri: str, content_type: str = "other"
) -> dict:
    """Trigger a video reframe (orientation change) job."""
    return await _create_job(
        "/api/v1/reframe",
        invite_code,
        {"gcs_uri": gcs_uri, "content_type": content_type},
    )


async def create_thumbnails(invite_code: str, gcs_uri: str, prompt_id: str) -> dict:
    """Trigger a thumbnail generation/analysis job."""
    return await _create_job(
        "/api/v1/thumbnails/analyze",
        invite_code,
        {
            "gcs_uri": gcs_uri,
            "prompt_id": prompt_id,
        },
    )


async def create_adapt(
    invite_code: str, gcs_uri: str, aspect_ratios: List[str]
) -> dict:
    """Trigger an Adapt job to resize video for multiple platforms."""
    return await _create_job(
        "/api/v1/adapts",
        invite_code,
        {
            "gcs_uri": gcs_uri,
            "aspect_ratios": aspect_ratios,
        },
    )


async def list_recent_adapts(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent social media adaptation jobs."""
    return await _list_recent("/api/v1/adapts", invite_code, limit)


async def list_recent_reframes(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video reframe (orientation) jobs."""
    return await _list_recent("/api/v1/reframe", invite_code, limit)


async def list_recent_key_moments(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent key moments analysis jobs."""
    return await _list_recent("/api/v1/key-moments", invite_code, limit)


async def list_recent_thumbnails(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent thumbnail jobs."""
    return await _list_recent("/api/v1/thumbnails", invite_code, limit)


async def list_content_types(invite_code: str) -> List[dict]:
    """Return valid content types for video reframing."""
    return await _api_call("GET", "/api/v1/system/lookups/content-types", invite_code)


async def list_aspect_ratios(invite_code: str) -> dict:
    """Return valid aspect ratios and preset bundles for adapts."""
    return await _api_call("GET", "/api/v1/system/lookups/aspect-ratios", invite_code)


async def list_prompt_categories(invite_code: str) -> List[dict]:
    """Return distinct prompt categories from the database."""
    return await _api_call(
        "GET", "/api/v1/system/lookups/prompt-categories", invite_code
    )


async def list_system_prompts(
    invite_code: str, category: Optional[str] = None
) -> List[dict]:
    """List available system prompts/resources, optionally filtered by category."""
    params: dict = {"type": "prompt"}
    if category:
        params["category"] = category
    return await _api_call(
        "GET", "/api/v1/system/resources", invite_code, params=params
    )


# ── Pricing tools ────────────────────────────────────────────────────


async def get_pricing_rates(invite_code: str) -> dict:
    """Get the catalog of current per-service pricing (text models, image models,
    Veo tiers, Cloud Transcoder, Speech V2 diarization)."""
    return await _api_call("GET", "/api/v1/pricing/rates", invite_code)


async def get_feature_services(invite_code: str) -> dict:
    """Get the map of features (production, adapts, reframe, promo, key_moments,
    thumbnails) to the services each one consumes, with rates inlined."""
    return await _api_call("GET", "/api/v1/pricing/features", invite_code)


async def estimate_cost(invite_code: str, payload: dict) -> dict:
    """Estimate the cost of a job before it runs. Payload must include
    `feature` (one of production/adapts/reframe/promo/key_moments/thumbnails)
    plus feature-specific inputs (scene_count, variant_count,
    source_duration_seconds, segment_count, thumbnail_count, etc.)."""
    return await _api_call(
        "POST", "/api/v1/pricing/estimate", invite_code, json=payload
    )


async def get_job_cost(invite_code: str, feature: str, record_id: str) -> dict:
    """Get the per-service cost breakdown for a completed (or in-progress) job.
    Returns line items, total cost, and pricing_confidence ('high'/'medium'/'low')
    plus notes describing any estimated fields."""
    return await _api_call(
        "GET", f"/api/v1/pricing/usage/{feature}/{record_id}", invite_code
    )


# Feature → list endpoint (for list_recent_jobs — lets Aanya resolve references
# like "my last production" without needing to know each specialist's tool).
_LIST_ENDPOINTS = {
    "production": "/api/v1/productions",
    "adapts": "/api/v1/adapts",
    "reframe": "/api/v1/reframe",
    "promo": "/api/v1/promo",
    "key_moments": "/api/v1/key-moments",
    "thumbnails": "/api/v1/thumbnails",
}


async def list_recent_jobs(
    invite_code: str, feature: str, limit: int = 5
) -> List[dict]:
    """List the most recent records for any feature, sorted newest-first.

    Returns a list of summary dicts with {id, name, status, createdAt}. Used
    by the orchestrator to resolve relative references like "my last production"
    or "the previous reframe" before calling get_job_cost.
    """
    endpoint = _LIST_ENDPOINTS.get(feature)
    if not endpoint:
        return [{"error": f"Unknown feature: {feature}"}]
    result = await _api_call("GET", endpoint, invite_code)
    if not isinstance(result, list):
        return [{"error": "Unexpected response", "detail": str(result)[:200]}]

    def _created(r: dict):
        return r.get("createdAt") or r.get("created_at") or ""

    sorted_records = sorted(result, key=_created, reverse=True)[:limit]
    return [
        {
            "id": r.get("id"),
            "name": r.get("name")
            or r.get("display_name")
            or r.get("source_filename")
            or "(unnamed)",
            "status": r.get("status", ""),
            "createdAt": _created(r),
        }
        for r in sorted_records
    ]

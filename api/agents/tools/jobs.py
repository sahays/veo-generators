"""Job CRUD + recent-list tools for every feature the orchestrator can route to."""

from typing import List, Optional

from ._client import api_call, create_job, list_recent

# Feature → endpoint map. Used both by `get_job_status` (looks up a single
# record) and `list_recent_jobs` (lists most recent for any feature). One
# table beats two parallel ones drifting apart.
_FEATURE_ENDPOINTS = {
    "production": "/api/v1/productions",
    "adapts": "/api/v1/adapts",
    "reframe": "/api/v1/reframe",
    "promo": "/api/v1/promo",
    "key_moments": "/api/v1/key-moments",
    "thumbnails": "/api/v1/thumbnails",
}


# ── Production ──────────────────────────────────────────────────────────────


async def list_recent_productions(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video production projects."""
    return await list_recent("/api/v1/productions", invite_code, limit)


async def create_production(
    invite_code: str, name: str, base_concept: str, prompt_id: Optional[str] = None
) -> dict:
    """Create a new video production project."""
    payload: dict = {"name": name, "base_concept": base_concept}
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return await create_job("/api/v1/productions", invite_code, payload)


# ── Promo ───────────────────────────────────────────────────────────────────


async def list_recent_promos(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent promotional video jobs."""
    return await list_recent("/api/v1/promo", invite_code, limit)


async def create_promo(
    invite_code: str,
    gcs_uri: str,
    target_duration: int = 60,
    source_filename: str = "",
    text_overlay: bool = False,
) -> dict:
    """Trigger a new promotional video generation job."""
    return await create_job(
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
    return await api_call("GET", "/api/v1/promo/sources/uploads", invite_code)


# ── Reframe / Key Moments / Thumbnails / Adapts ─────────────────────────────


async def list_recent_reframes(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video reframe (orientation) jobs."""
    return await list_recent("/api/v1/reframe", invite_code, limit)


async def create_reframe(
    invite_code: str, gcs_uri: str, content_type: str = "other"
) -> dict:
    """Trigger a video reframe (orientation change) job."""
    return await create_job(
        "/api/v1/reframe",
        invite_code,
        {"gcs_uri": gcs_uri, "content_type": content_type},
    )


async def list_recent_key_moments(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent key moments analysis jobs."""
    return await list_recent("/api/v1/key-moments", invite_code, limit)


async def create_key_moments_analysis(
    invite_code: str, gcs_uri: str, prompt_id: str
) -> dict:
    """Trigger a Key Moments analysis for a video."""
    return await create_job(
        "/api/v1/key-moments/analyze",
        invite_code,
        {"gcs_uri": gcs_uri, "prompt_id": prompt_id},
    )


async def list_recent_thumbnails(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent thumbnail jobs."""
    return await list_recent("/api/v1/thumbnails", invite_code, limit)


async def create_thumbnails(invite_code: str, gcs_uri: str, prompt_id: str) -> dict:
    """Trigger a thumbnail generation/analysis job."""
    return await create_job(
        "/api/v1/thumbnails/analyze",
        invite_code,
        {"gcs_uri": gcs_uri, "prompt_id": prompt_id},
    )


async def list_recent_adapts(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent social media adaptation jobs."""
    return await list_recent("/api/v1/adapts", invite_code, limit)


async def create_adapt(
    invite_code: str, gcs_uri: str, aspect_ratios: List[str]
) -> dict:
    """Trigger an Adapt job to resize video for multiple platforms."""
    return await create_job(
        "/api/v1/adapts",
        invite_code,
        {"gcs_uri": gcs_uri, "aspect_ratios": aspect_ratios},
    )


# ── Cross-feature helpers ───────────────────────────────────────────────────


async def get_job_status(invite_code: str, job_type: str, job_id: str) -> dict:
    """Check the status of a specific job."""
    endpoint = _FEATURE_ENDPOINTS.get(job_type)
    if not endpoint:
        return {"error": f"Unknown job type: {job_type}"}
    return await api_call("GET", f"{endpoint}/{job_id}", invite_code)


def _record_summary(record: dict) -> dict:
    return {
        "id": record.get("id"),
        "name": record.get("name")
        or record.get("display_name")
        or record.get("source_filename")
        or "(unnamed)",
        "status": record.get("status", ""),
        "createdAt": record.get("createdAt") or record.get("created_at") or "",
    }


async def list_recent_jobs(
    invite_code: str, feature: str, limit: int = 5
) -> List[dict]:
    """List the most recent records for any feature, sorted newest-first.

    Returns summary dicts ({id, name, status, createdAt}) — used by Aanya to
    resolve relative references like "my last production" before calling
    `get_job_cost`.
    """
    endpoint = _FEATURE_ENDPOINTS.get(feature)
    if not endpoint:
        return [{"error": f"Unknown feature: {feature}"}]
    result = await api_call("GET", endpoint, invite_code)
    if not isinstance(result, list):
        return [{"error": "Unexpected response", "detail": str(result)[:200]}]
    sorted_records = sorted(
        result,
        key=lambda r: r.get("createdAt") or r.get("created_at") or "",
        reverse=True,
    )[:limit]
    return [_record_summary(r) for r in sorted_records]

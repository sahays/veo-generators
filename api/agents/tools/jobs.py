"""Job CRUD + recent-list tools for every feature specialist."""

from typing import List, Optional

from ._client import api_call, create_job, list_recent

# Feature → endpoint map. Used both by `get_job_status` (looks up a single
# record) and `list_recent_jobs` (lists most recent for any feature).
_FEATURE_ENDPOINTS = {
    "production": "/api/v1/productions",
    "adapts": "/api/v1/adapts",
    "reframe": "/api/v1/reframe",
    "promo": "/api/v1/promo",
    "key_moments": "/api/v1/key-moments",
    "thumbnails": "/api/v1/thumbnails",
    "dubbing": "/api/v1/dubbing",
}

_FEATURE_ALIASES = {
    "productions": "production",
    "projects": "production",
    "project": "production",
    "orientation": "reframe",
    "orientations": "reframe",
    "reframes": "reframe",
    "promos": "promo",
    "key-moments": "key_moments",
    "key_moment": "key_moments",
    "thumbnail": "thumbnails",
    "adapt": "adapts",
    "dubs": "dubbing",
    "dub": "dubbing",
}


def normalize_feature(feature: str) -> str:
    key = (feature or "").strip().lower()
    return _FEATURE_ALIASES.get(key, key)


# ── Production ──────────────────────────────────────────────────────────────


async def list_recent_productions(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video production projects."""
    return await list_recent("/api/v1/productions", invite_code, limit)


async def create_production(
    invite_code: str,
    name: str,
    base_concept: str,
    prompt_id: Optional[str] = None,
    video_length: str = "16",
    orientation: str = "16:9",
    project_type: str = "advertizement",
    language: str = "en-IN",
) -> dict:
    """Create a new video production project."""
    payload: dict = {
        "name": name,
        "base_concept": base_concept,
        "video_length": str(video_length),
        "orientation": orientation,
        "type": project_type,
        "language": language,
    }
    if prompt_id:
        payload["prompt_id"] = prompt_id
    return await create_job("/api/v1/productions", invite_code, payload)


async def trigger_production_step(
    invite_code: str,
    production_id: str,
    step: str,
    payload: Optional[dict] = None,
) -> dict:
    """Trigger a lifecycle step ('analyze', 'review', 'render', 'render-draft', 'upgrade-final', 'evaluate', 'regenerate-flagged', 'generate-storyboard', 'generate-videos', 'stitch') on a production."""
    if step == "render-draft":
        body = {"quality": "draft", "resolution": "360p", **(payload or {})}
        return await api_call(
            "POST",
            f"/api/v1/productions/{production_id}/render",
            invite_code,
            json=body,
        )
    if step in ("upgrade-final", "render-final"):
        body = {"quality": "final", "resolution": "720p", **(payload or {})}
        return await api_call(
            "POST",
            f"/api/v1/productions/{production_id}/render",
            invite_code,
            json=body,
        )
    return await api_call(
        "POST",
        f"/api/v1/productions/{production_id}/{step}",
        invite_code,
        json=payload or {},
    )


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


async def trigger_thumbnail_step(invite_code: str, record_id: str, step: str) -> dict:
    """Trigger 'capture-frames' or 'generate-collage' on an analyzed thumbnail record."""
    return await api_call(
        "POST", f"/api/v1/thumbnails/{record_id}/{step}", invite_code, json={}
    )


async def list_recent_adapts(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent social media adaptation jobs."""
    return await list_recent("/api/v1/adapts", invite_code, limit)


async def create_adapt(
    invite_code: str, gcs_uri: str, aspect_ratios: List[str]
) -> dict:
    """Trigger an Adapt job to resize an image for multiple platforms."""
    return await create_job(
        "/api/v1/adapts",
        invite_code,
        {"gcs_uri": gcs_uri, "aspect_ratios": aspect_ratios},
    )


# ── Dubbing ─────────────────────────────────────────────────────────────────


async def list_dubbing_languages(invite_code: str) -> List[dict]:
    """Return the allowlist of target languages supported by Dubbing."""
    return await api_call("GET", "/api/v1/dubbing/languages", invite_code)


async def list_recent_dubbing(invite_code: str, limit: int = 5) -> List[dict]:
    """List the most recent video dubbing jobs."""
    return await list_recent("/api/v1/dubbing", invite_code, limit)


async def create_dubbing(
    invite_code: str,
    gcs_uri: str,
    target_languages: List[str],
    source_filename: str = "",
) -> dict:
    """Create a multi-language video dubbing job."""
    return await create_job(
        "/api/v1/dubbing",
        invite_code,
        {
            "gcs_uri": gcs_uri,
            "target_languages": target_languages,
            "source_filename": source_filename,
        },
    )


async def retry_dubbing(invite_code: str, record_id: str) -> dict:
    """Retry failed or unfinished language variants on a dubbing job."""
    return await api_call(
        "POST", f"/api/v1/dubbing/{record_id}/retry", invite_code, json={}
    )


# ── FinOps / Models / Uploads ───────────────────────────────────────────────


async def list_ai_models(invite_code: str) -> List[dict]:
    """List registered AI models and their active regions."""
    res = await api_call("GET", "/api/v1/models", invite_code)
    return res if isinstance(res, list) else []


async def list_uploads(
    invite_code: str, file_type: Optional[str] = None, limit: int = 10
) -> List[dict]:
    """List uploaded media files."""
    params = {"file_type": file_type} if file_type else None
    res = await api_call("GET", "/api/v1/uploads", invite_code, params=params)
    return res[:limit] if isinstance(res, list) else []


# ── Cross-feature helpers ───────────────────────────────────────────────────


async def get_job_status(invite_code: str, job_type: str, job_id: str) -> dict:
    """Check the status of a specific job."""
    endpoint = _FEATURE_ENDPOINTS.get(normalize_feature(job_type))
    if not endpoint:
        return {"error": f"Unknown job type: {job_type}"}
    return await api_call("GET", f"{endpoint}/{job_id}", invite_code)


def _record_summary(record: dict) -> dict:
    summary = {
        "id": record.get("id"),
        "name": record.get("name")
        or record.get("display_name")
        or record.get("source_filename")
        or "(unnamed)",
        "status": record.get("status", ""),
        "createdAt": record.get("createdAt") or record.get("created_at") or "",
    }
    usage = record.get("usage") or record.get("total_usage")
    if usage:
        summary["usage"] = usage
    for extra_key in (
        "pipeline_stage",
        "render_quality",
        "video_resolution",
        "pipeline_steps",
        "review_report",
        "eval_report",
    ):
        val = record.get(extra_key)
        if val is not None:
            summary[extra_key] = val
    return summary


async def list_recent_jobs(
    invite_code: str, feature: str, limit: int = 5
) -> List[dict]:
    """List the most recent records for any feature, sorted newest-first."""
    norm_feature = normalize_feature(feature)
    endpoint = _FEATURE_ENDPOINTS.get(norm_feature)
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

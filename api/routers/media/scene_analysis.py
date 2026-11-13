"""Scene analysis router: timestamped timelines of uploaded or produced videos.

The API only queues work. `POST` writes a `pending` record that the worker's
`SceneAnalysisProcessor` picks up; the finished `timeline.json` is served from
GCS by `GET /{id}/timeline`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import deps
from helpers import (
    ensure_services_ready,
    get_or_404,
    list_completed_production_sources,
    list_video_upload_sources,
    sign_record_urls,
)
from insight_records import build_scene_analysis_record, requeue_updates
from models import SceneAnalysisRecord
from routers._crud import register_crud_routes
from source_resolver import resolve_video_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scene-analysis", tags=["scene-analysis"])

RESOURCE_LABEL = "Scene analysis"
GCS_PREFIX = "scene_analysis"
_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
_MODEL_PATTERN = r"^[A-Za-z0-9._\-]+$"


class SceneAnalysisCreate(BaseModel):
    """Create payload. The video is named by id; a `gs://` URI is never accepted."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    source_type: Literal["upload", "production"]
    source_id: str = Field(min_length=1, max_length=128, pattern=_ID_PATTERN)
    focus: str = Field(default="", max_length=500)
    display_name: str = Field(default="", max_length=200)
    model_id: Optional[str] = Field(
        default=None, max_length=100, pattern=_MODEL_PATTERN
    )
    region: Optional[str] = Field(default=None, max_length=64, pattern=_MODEL_PATTERN)


def _log_ctx(where: str, what: str, why: str, how: str) -> dict[str, str]:
    return {
        "who": "scene_analysis_router",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


def _sign(record: SceneAnalysisRecord) -> dict[str, Any]:
    """Record dict with a signed URL for the source video."""
    return sign_record_urls(
        record,
        {"video_gcs_uri": "video_signed_url"},
        lambda cache: deps.firestore_svc.update_scene_analysis(
            record.id, {"signed_urls": cache}
        ),
    )


def _require_no_dependants(record_id: str) -> None:
    """Refuse (409) to delete an analysis that engagement reports still read."""
    count = len(deps.firestore_svc.find_engagements_for_analysis(record_id))
    if not count:
        return
    logger.warning(
        f"Scene analysis {record_id} not deleted: {count} engagement report(s) use it",
        extra=_log_ctx(
            "_require_no_dependants",
            f"delete_blocked:{record_id}",
            f"dependants={count}",
            "http_409",
        ),
    )
    reports = (
        "1 engagement report uses" if count == 1 else f"{count} engagement reports use"
    )
    raise HTTPException(
        status_code=409,
        detail=f"{reports} this scene analysis. Delete them first.",
    )


def _delete_with_assets(record_id: str) -> None:
    """Delete the record and only the GCS objects under its own prefix.

    Blocked while engagement records depend on it: their workspaces read this
    analysis's timeline.
    """
    _require_no_dependants(record_id)
    if deps.storage_svc:
        deleted = deps.storage_svc.delete_prefix(f"{GCS_PREFIX}/{record_id}/")
        logger.info(
            f"Purged {deleted} object(s) for scene analysis {record_id}",
            extra=_log_ctx(
                "_delete_with_assets", f"purged={deleted}", "record_deleted", record_id
            ),
        )
    deps.firestore_svc.delete_scene_analysis(record_id)


register_crud_routes(
    router,
    resource_label=RESOURCE_LABEL,
    getter=lambda rid: deps.firestore_svc.get_scene_analysis(rid),
    updater=lambda rid, u: deps.firestore_svc.update_scene_analysis(rid, u),
    deleter=_delete_with_assets,
    lister=lambda include_archived=False: deps.firestore_svc.get_scene_analyses(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
    retry_updates_fn=requeue_updates,
)


@router.get("/sources/uploads")
async def list_scene_analysis_upload_sources() -> list[dict[str, Any]]:
    """List uploaded video files that can be analysed."""
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_scene_analysis_production_sources() -> list[dict[str, Any]]:
    """List completed studio productions that can be analysed."""
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


@router.post("")
async def create_scene_analysis(
    body: SceneAnalysisCreate, request: Request
) -> dict[str, str]:
    """Queue a scene analysis of a known upload or production."""
    ensure_services_ready()
    source = resolve_video_source(body.source_type, body.source_id)
    record = build_scene_analysis_record(
        source,
        display_name=body.display_name,
        focus=body.focus,
        model_id=body.model_id,
        region=body.region,
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_scene_analysis(record)
    logger.info(
        f"Scene analysis {record.id} queued",
        extra=_log_ctx(
            "create_scene_analysis",
            f"queued:{record.id}",
            f"{source.source_type}:{source.source_id}",
            "create_scene_analysis",
        ),
    )
    return {"id": record.id, "status": record.status}


def _filmstrip_info(record: SceneAnalysisRecord) -> Optional[dict[str, Any]]:
    """Sprite layout plus a signed URL, or None when no filmstrip was produced."""
    if not (record.filmstrip and record.filmstrip_gcs_uri and deps.storage_svc):
        return None
    url = deps.storage_svc.get_signed_url(record.filmstrip_gcs_uri)
    return {**record.filmstrip.model_dump(), "url": url}


def _load_timeline(record: SceneAnalysisRecord) -> dict[str, Any]:
    """Read and parse the record's `timeline.json` from GCS."""
    timeline = json.loads(deps.storage_svc.download_bytes(record.timeline_gcs_uri))
    if not isinstance(timeline, dict):
        raise ValueError("timeline.json is not a JSON object")
    return {"timeline": timeline, "filmstrip": _filmstrip_info(record)}


@router.get("/{record_id}/timeline")
async def get_scene_analysis_timeline(record_id: str) -> dict[str, Any]:
    """Return the timeline document and filmstrip of a completed analysis."""
    ensure_services_ready()
    record = get_or_404(
        deps.firestore_svc.get_scene_analysis, record_id, RESOURCE_LABEL
    )
    if record.status != "completed" or not record.timeline_gcs_uri:
        raise HTTPException(status_code=409, detail="Scene analysis is not completed")
    if not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        return await asyncio.to_thread(_load_timeline, record)
    except Exception as exc:
        logger.error(
            f"Timeline for scene analysis {record.id} could not be read: {exc}",
            extra=_log_ctx(
                "get_scene_analysis_timeline",
                f"timeline_read_failed:{record.id}",
                str(exc),
                "download_bytes",
            ),
        )
        raise HTTPException(status_code=502, detail="Timeline is unavailable")

"""Dubbing API — create and manage multi-language dubbing jobs.

Creation only records a `pending` job; the worker does the dubbing. Mirrors the
adapts router, which has the same one-source-many-variants shape.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import deps
from dubbing_config import (
    language_regions,
    max_languages,
    max_source_minutes,
    supported_languages,
)
from helpers import (
    ensure_services_ready,
    list_completed_production_sources,
    list_video_upload_sources,
    sign_record_urls,
)
from models import DubRecord, DubVariant
from routers._crud import register_crud_routes
from url_signing import sign_nested_list_uris

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/dubbing", tags=["dubbing"])


class DubRequest(BaseModel):
    gcs_uri: str
    source_filename: str = ""
    language_codes: list[str] = []
    duration_sec: float = 0.0  # client-known duration, used for the length guard
    model_id: Optional[str] = None


def _sign(record: DubRecord) -> dict[str, Any]:
    """Sign source video and per-variant dubbed video/SRT URIs."""
    data = sign_record_urls(
        record,
        {"source_gcs_uri": "source_signed_url"},
        lambda cache: deps.firestore_svc.update_dub_record(
            record.id, {"signed_urls": cache}
        ),
    )
    sign_nested_list_uris(data, "variants", "output_gcs_uri", "output_signed_url")
    sign_nested_list_uris(data, "variants", "srt_gcs_uri", "srt_signed_url")
    return data


def _dub_retry_updates(record: DubRecord) -> dict[str, Any]:
    """Retry only what failed — completed languages keep their output."""
    variants = [v.dict() for v in record.variants]
    for v in variants:
        if v["status"] != "completed":
            v.update(status="pending", error_message=None, output_gcs_uri=None)
    return {
        "status": "pending",
        "error_message": None,
        "progress_pct": 0,
        "variants": variants,
    }


@router.get("/languages")
async def list_languages() -> dict[str, Any]:
    """Target languages the UI may offer — served from the allowlist."""
    regions = language_regions()
    return {
        "languages": [
            {"code": code, "name": name, "region": regions.get(code, "Other")}
            for code, name in supported_languages().items()
        ],
        "max_languages": max_languages(),
        "max_source_minutes": max_source_minutes(),
    }


register_crud_routes(
    router,
    resource_label="Dub record",
    getter=lambda rid: deps.firestore_svc.get_dub_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_dub_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_dub_record(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_dub_records(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
    retry_updates_fn=_dub_retry_updates,
)


@router.get("/sources/uploads")
async def list_dub_upload_sources() -> list[dict[str, Any]]:
    """List uploaded video files eligible for dubbing."""
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_dub_production_sources() -> list[dict[str, Any]]:
    """List completed studio productions eligible for dubbing."""
    return list_completed_production_sources()


def _validate_languages(codes: list[str]) -> list[str]:
    """Allowlist check plus a fan-out cap."""
    allowed = supported_languages()
    unique = list(dict.fromkeys(codes))
    if not unique:
        raise HTTPException(400, "Select at least one target language")
    unknown = [c for c in unique if c not in allowed]
    if unknown:
        raise HTTPException(
            400,
            f"Unsupported language code(s): {', '.join(sorted(unknown))}. "
            f"Supported: {', '.join(sorted(allowed))}",
        )
    if len(unique) > max_languages():
        raise HTTPException(
            400, f"At most {max_languages()} languages per job (got {len(unique)})"
        )
    return unique


@router.post("")
async def create_dub(body: DubRequest, request: Request) -> dict[str, str]:
    """Create a dubbing job. The worker picks it up from Firestore."""
    ensure_services_ready()
    languages = _validate_languages(body.language_codes)
    limit_min = max_source_minutes()
    if body.duration_sec and body.duration_sec > limit_min * 60:
        raise HTTPException(
            400,
            f"Source is {body.duration_sec / 60:.1f} min; the limit is {limit_min:.0f} min",
        )
    record = DubRecord(
        source_gcs_uri=body.gcs_uri,
        source_filename=body.source_filename,
        duration_sec=body.duration_sec,
        model_id=body.model_id,
        variants=[DubVariant(language_code=code) for code in languages],
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_dub_record(record)
    logger.info(
        f"[dub:{record.id}] queued for {', '.join(languages)}",
        extra={
            "who": "dubbing_router",
            "where": "create_dub",
            "what": "dub_job_queued",
            "why": f"languages={','.join(languages)}",
            "how": "firestore_create",
        },
    )
    return {"id": record.id, "status": record.status}

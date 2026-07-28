"""Dubbing API — create and manage multi-language dubbing jobs.

Creation only records a `pending` job; the worker does the dubbing. Mirrors the
adapts router, which has the same one-source-many-variants shape.
"""

import logging
from typing import Optional

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
    list_completed_production_sources,
    list_video_upload_sources,
    require_firestore,
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


def _sign(record: DubRecord) -> dict:
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


def _dub_retry_updates(record: DubRecord) -> dict:
    """Retry only what failed — completed languages keep their output rather
    than being re-dubbed at full cost."""
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


# Registered BEFORE the CRUD routes on purpose: FastAPI matches in registration
# order, and `register_crud_routes` adds a `GET /{record_id}` that would
# otherwise swallow this single-segment path and treat "languages" as an id.
# (The `/sources/*` routes below are two segments, so they never collide.)
@router.get("/languages")
async def list_languages():
    """Target languages the UI may offer — served from the allowlist so the
    picker is never a second hardcoded list that can drift from it.

    Emitted in table order rather than sorted here: the table's order *is* the
    display order, and re-sorting would scatter the region groups.
    """
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
async def list_dub_upload_sources():
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_dub_production_sources():
    return list_completed_production_sources()


def _validate_languages(codes: list[str]) -> list[str]:
    """Allowlist check plus a fan-out cap.

    Deduplicated while preserving order, so a repeated code cannot multiply the
    work past the cap. Unknown codes are rejected here, before they can reach a
    GCS path or the Live API.
    """
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
async def create_dub(body: DubRequest, request: Request):
    """Create a dubbing job. The worker picks it up from Firestore."""
    require_firestore()
    languages = _validate_languages(body.language_codes)

    # Cheap pre-check on the client-reported duration so an obviously oversized
    # job is refused before it occupies the single worker instance. The worker
    # re-checks against the real ffprobe duration, which is the authority.
    limit_min = max_source_minutes()
    if body.duration_sec and body.duration_sec > limit_min * 60:
        raise HTTPException(
            400,
            f"Source is {body.duration_sec / 60:.1f} min; the limit is "
            f"{limit_min:.0f} min",
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
    logger.info(f"[dub:{record.id}] queued for {', '.join(languages)}")
    return {"id": record.id, "status": record.status}

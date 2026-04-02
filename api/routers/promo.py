import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import deps
from helpers import (
    get_or_404,
    list_completed_production_sources,
    list_video_upload_sources,
    require_firestore,
    sign_record_urls,
)
from models import PromoRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/promo", tags=["promo"])


class PromoRequest(BaseModel):
    gcs_uri: str
    source_filename: str = ""
    mime_type: str = "video/mp4"
    prompt_id: str = ""
    target_duration: int = 60
    text_overlay: bool = False
    generate_thumbnail: bool = False


def _sign_promo_urls(record: PromoRecord) -> dict:
    data = sign_record_urls(
        record,
        {
            "source_gcs_uri": "source_signed_url",
            "output_gcs_uri": "output_signed_url",
            "thumbnail_gcs_uri": "thumbnail_signed_url",
        },
        lambda cache: deps.firestore_svc.update_promo_record(
            record.id, {"signed_urls": cache}
        ),
    )
    # Resolve prompt name for display
    if record.prompt_id and deps.firestore_svc:
        res = deps.firestore_svc.get_resource(record.prompt_id)
        if res:
            data["prompt_name"] = res.name
    # Sign overlay image URIs per segment
    if deps.storage_svc and data.get("segments"):
        _cache: dict = {}
        for seg in data["segments"]:
            uri = seg.get("overlay_gcs_uri")
            if uri:
                url, _ = deps.storage_svc.resolve_cached_url(uri, _cache)
                seg["overlay_signed_url"] = url
    return data


@router.get("")
async def list_promos(request: Request, archived: bool = False):
    require_firestore()
    records = deps.firestore_svc.get_promo_records(include_archived=archived)
    return [_sign_promo_urls(r) for r in records]


@router.get("/sources/uploads")
async def list_promo_upload_sources():
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_promo_production_sources():
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


@router.get("/{record_id}")
async def get_promo(record_id: str):
    require_firestore()
    record = get_or_404(deps.firestore_svc.get_promo_record, record_id, "Promo record")
    return _sign_promo_urls(record)


@router.post("")
async def create_promo(body: PromoRequest, request: Request):
    """Create a promo job. Worker picks it up from Firestore."""
    require_firestore()

    record = PromoRecord(
        source_gcs_uri=body.gcs_uri,
        source_filename=body.source_filename,
        prompt_id=body.prompt_id,
        target_duration=body.target_duration,
        text_overlay=body.text_overlay,
        generate_thumbnail=body.generate_thumbnail,
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_promo_record(record)

    return {"id": record.id, "status": record.status}


@router.post("/{record_id}/retry")
async def retry_promo(record_id: str):
    """Reset a failed promo to pending so the worker retries it.

    Preserves segments, thumbnail, and overlay data so expensive Gemini
    calls are not repeated.
    """
    require_firestore()
    record = get_or_404(deps.firestore_svc.get_promo_record, record_id, "Promo record")
    if record.status in ("pending", "completed"):
        raise HTTPException(400, f"Cannot retry a {record.status} promo")
    deps.firestore_svc.update_promo_record(
        record_id,
        {"status": "pending", "error_message": None, "progress_pct": 0},
    )
    return {"id": record_id, "status": "pending"}


@router.patch("/{record_id}")
async def update_promo(record_id: str, body: dict):
    require_firestore()
    get_or_404(deps.firestore_svc.get_promo_record, record_id, "Promo record")
    updates = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    deps.firestore_svc.update_promo_record(record_id, updates)
    return {"status": "updated"}


@router.post("/{record_id}/archive")
async def archive_promo(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_promo_record, record_id, "Promo record")
    deps.firestore_svc.update_promo_record(record_id, {"archived": True})
    return {"status": "archived"}


@router.delete("/{record_id}")
async def delete_promo(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_promo_record, record_id, "Promo record")
    deps.firestore_svc.delete_promo_record(record_id)
    return {"status": "deleted"}

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
from models import ReframeRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reframe", tags=["reframe"])


class ReframeRequest(BaseModel):
    gcs_uri: str
    source_filename: str = ""
    mime_type: str = "video/mp4"
    prompt_id: str = ""
    content_type: str = "other"
    blurred_bg: bool = False
    sports_mode: bool = False  # deprecated — use content_type="sports"
    vertical_split: bool = False


def _sign_reframe_urls(record: ReframeRecord) -> dict:
    return sign_record_urls(
        record,
        {"source_gcs_uri": "source_signed_url", "output_gcs_uri": "output_signed_url"},
        lambda cache: deps.firestore_svc.update_reframe_record(
            record.id, {"signed_urls": cache}
        ),
    )


@router.get("")
async def list_reframes(request: Request, archived: bool = False):
    require_firestore()
    records = deps.firestore_svc.get_reframe_records(include_archived=archived)
    return [_sign_reframe_urls(r) for r in records]


@router.get("/sources/uploads")
async def list_reframe_upload_sources():
    """List uploaded videos that can be reframed."""
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_reframe_production_sources():
    """List completed productions with signed final video URLs."""
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


@router.get("/{record_id}")
async def get_reframe(record_id: str):
    require_firestore()
    record = get_or_404(
        deps.firestore_svc.get_reframe_record, record_id, "Reframe record"
    )
    return _sign_reframe_urls(record)


@router.post("")
async def create_reframe(
    body: ReframeRequest,
    request: Request,
):
    """Create a reframe job. Worker picks it up from Firestore."""
    require_firestore()

    # Backward compat: sports_mode=True maps to content_type="sports"
    content_type = body.content_type
    if body.sports_mode and content_type == "other":
        content_type = "sports"

    record = ReframeRecord(
        source_gcs_uri=body.gcs_uri,
        source_filename=body.source_filename,
        prompt_id=body.prompt_id,
        content_type=content_type,
        blurred_bg=body.blurred_bg,
        sports_mode=body.sports_mode,
        vertical_split=body.vertical_split,
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_reframe_record(record)

    return {"id": record.id, "status": record.status}


@router.post("/{record_id}/retry")
async def retry_reframe(record_id: str):
    """Reset a failed reframe to pending so the worker retries it."""
    require_firestore()
    record = get_or_404(
        deps.firestore_svc.get_reframe_record, record_id, "Reframe record"
    )
    if record.status in ("pending", "completed"):
        raise HTTPException(400, f"Cannot retry a {record.status} reframe")
    deps.firestore_svc.update_reframe_record(
        record_id,
        {"status": "pending", "error_message": None, "progress_pct": 0},
    )
    return {"id": record_id, "status": "pending"}


@router.patch("/{record_id}")
async def update_reframe(record_id: str, body: dict):
    require_firestore()
    get_or_404(deps.firestore_svc.get_reframe_record, record_id, "Reframe record")
    updates = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    deps.firestore_svc.update_reframe_record(record_id, updates)
    return {"status": "updated"}


@router.post("/{record_id}/archive")
async def archive_reframe(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_reframe_record, record_id, "Reframe record")
    deps.firestore_svc.update_reframe_record(record_id, {"archived": True})
    return {"status": "archived"}


@router.delete("/{record_id}")
async def delete_reframe(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_reframe_record, record_id, "Reframe record")
    deps.firestore_svc.delete_reframe_record(record_id)
    return {"status": "deleted"}

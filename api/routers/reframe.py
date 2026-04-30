import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

import deps
from helpers import (
    list_completed_production_sources,
    list_video_upload_sources,
    require_firestore,
    sign_record_urls,
)
from models import ReframeRecord
from routers._crud import register_crud_routes

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
    model_id: Optional[str] = None
    region: Optional[str] = None


def _sign(record: ReframeRecord) -> dict:
    return sign_record_urls(
        record,
        {"source_gcs_uri": "source_signed_url", "output_gcs_uri": "output_signed_url"},
        lambda cache: deps.firestore_svc.update_reframe_record(
            record.id, {"signed_urls": cache}
        ),
    )


register_crud_routes(
    router,
    resource_label="Reframe record",
    getter=lambda rid: deps.firestore_svc.get_reframe_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_reframe_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_reframe_record(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_reframe_records(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
)


@router.get("/sources/uploads")
async def list_reframe_upload_sources():
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_reframe_production_sources():
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


@router.post("")
async def create_reframe(body: ReframeRequest, request: Request):
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
        model_id=body.model_id,
        region=body.region,
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_reframe_record(record)
    return {"id": record.id, "status": record.status}

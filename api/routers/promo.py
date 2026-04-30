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
from models import PromoRecord
from routers._crud import register_crud_routes

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
    model_id: Optional[str] = None
    region: Optional[str] = None


def _sign(record: PromoRecord) -> dict:
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
    if record.prompt_id and deps.firestore_svc:
        res = deps.firestore_svc.get_resource(record.prompt_id)
        if res:
            data["prompt_name"] = res.name
    if deps.storage_svc and data.get("segments"):
        _cache: dict = {}
        for seg in data["segments"]:
            uri = seg.get("overlay_gcs_uri")
            if uri:
                url, _ = deps.storage_svc.resolve_cached_url(uri, _cache)
                seg["overlay_signed_url"] = url
    return data


register_crud_routes(
    router,
    resource_label="Promo record",
    getter=lambda rid: deps.firestore_svc.get_promo_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_promo_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_promo_record(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_promo_records(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
)


@router.get("/sources/uploads")
async def list_promo_upload_sources():
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_promo_production_sources():
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


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
        model_id=body.model_id,
        region=body.region,
        status="pending",
        invite_code=getattr(request.state, "invite_code", None),
    )
    deps.firestore_svc.create_promo_record(record)
    return {"id": record.id, "status": record.status}

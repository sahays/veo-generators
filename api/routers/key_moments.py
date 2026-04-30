import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from helpers import (
    list_completed_production_sources,
    sign_record_urls,
)
from models import KeyMomentsRecord
from routers._crud import register_crud_routes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/key-moments", tags=["key-moments"])


def _sign(record: KeyMomentsRecord) -> dict:
    return sign_record_urls(
        record,
        {"video_gcs_uri": "video_signed_url"},
        lambda cache: deps.firestore_svc.update_key_moments_analysis(
            record.id, {"signed_urls": cache}
        ),
    )


# Standard CRUD
register_crud_routes(
    router,
    resource_label="Analysis",
    getter=lambda rid: deps.firestore_svc.get_key_moments_analysis(rid),
    updater=lambda rid, u: deps.firestore_svc.update_key_moments_analysis(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_key_moments_analysis(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_key_moments_analyses(
        include_archived=include_archived
    ),
    sign_one=_sign,
)


# Feature-specific endpoints below
@router.get("/sources/productions")
async def list_production_sources():
    """List completed productions with signed final video URLs."""
    return list_completed_production_sources(extra_fields={"type": "type"})


@router.post("/analyze")
async def analyze_key_moments(request: Request, body: dict):
    if not deps.ai_svc or not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    gcs_uri = body.get("gcs_uri")
    prompt_id = body.get("prompt_id")
    if not gcs_uri or not prompt_id:
        raise HTTPException(
            status_code=400, detail="gcs_uri and prompt_id are required"
        )
    try:
        result = await deps.ai_svc.analyze_video_key_moments(
            gcs_uri=gcs_uri,
            mime_type=body.get("mime_type", "video/mp4"),
            prompt_id=prompt_id,
            schema_id=body.get("schema_id"),
            model_id=body.get("model_id"),
            region=body.get("region"),
        )
    except Exception as e:
        logger.error(f"Key moments analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    analysis_data = result.data if hasattr(result, "data") else result.get("data")
    moments = analysis_data.get("key_moments", []) if analysis_data else []
    record = KeyMomentsRecord(
        video_gcs_uri=gcs_uri,
        video_filename=body.get("video_filename", ""),
        video_source=body.get("video_source", "upload"),
        production_id=body.get("production_id"),
        mime_type=body.get("mime_type", "video/mp4"),
        prompt_id=prompt_id,
        invite_code=getattr(request.state, "invite_code", None),
        video_summary=analysis_data.get("video_summary") if analysis_data else None,
        key_moments=moments,
        moment_count=len(moments),
        usage=result.usage if hasattr(result, "usage") else result.get("usage", {}),
    )
    deps.firestore_svc.create_key_moments_analysis(record)
    return {"id": record.id, "data": analysis_data, "usage": record.usage.dict()}

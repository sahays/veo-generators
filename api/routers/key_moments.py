import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from helpers import (
    get_or_404,
    list_completed_production_sources,
    require_firestore,
    sign_record_urls,
)
from models import KeyMomentsRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/key-moments", tags=["key-moments"])


def _sign_key_moments_url(record: KeyMomentsRecord) -> dict:
    return sign_record_urls(
        record,
        {"video_gcs_uri": "video_signed_url"},
        lambda cache: deps.firestore_svc.key_moments_collection.document(
            record.id
        ).update({"signed_urls": cache}),
    )


@router.get("")
async def list_key_moments(request: Request, archived: bool = False):
    require_firestore()
    records = deps.firestore_svc.get_key_moments_analyses(include_archived=archived)
    return [_sign_key_moments_url(r) for r in records]


@router.get("/sources/productions")
async def list_production_sources():
    """List completed productions with signed final video URLs."""
    return list_completed_production_sources(extra_fields={"type": "type"})


@router.get("/{record_id}")
async def get_key_moments_analysis(record_id: str):
    require_firestore()
    record = get_or_404(
        deps.firestore_svc.get_key_moments_analysis, record_id, "Analysis"
    )
    return _sign_key_moments_url(record)


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
    mime_type = body.get("mime_type", "video/mp4")
    schema_id = body.get("schema_id")
    video_filename = body.get("video_filename", "")
    video_source = body.get("video_source", "upload")
    production_id = body.get("production_id")
    try:
        result = await deps.ai_svc.analyze_video_key_moments(
            gcs_uri=gcs_uri,
            mime_type=mime_type,
            prompt_id=prompt_id,
            schema_id=schema_id,
        )
        # Persist to Firestore
        analysis_data = result.data if hasattr(result, "data") else result.get("data")
        record = KeyMomentsRecord(
            video_gcs_uri=gcs_uri,
            video_filename=video_filename,
            video_source=video_source,
            production_id=production_id,
            mime_type=mime_type,
            prompt_id=prompt_id,
            invite_code=getattr(request.state, "invite_code", None),
            video_summary=(
                analysis_data.get("video_summary") if analysis_data else None
            ),
            key_moments=[
                m
                for m in (analysis_data.get("key_moments", []) if analysis_data else [])
            ],
            moment_count=len(
                analysis_data.get("key_moments", []) if analysis_data else []
            ),
            usage=(
                result.usage if hasattr(result, "usage") else result.get("usage", {})
            ),
        )
        deps.firestore_svc.create_key_moments_analysis(record)
        return {"id": record.id, "data": analysis_data, "usage": record.usage.dict()}
    except Exception as e:
        logger.error(f"Key moments analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{record_id}")
async def update_key_moments(record_id: str, body: dict):
    require_firestore()
    get_or_404(deps.firestore_svc.get_key_moments_analysis, record_id, "Analysis")
    updates = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    deps.firestore_svc.key_moments_collection.document(record_id).update(updates)
    return {"status": "updated"}


@router.post("/{record_id}/archive")
async def archive_key_moments_analysis(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_key_moments_analysis, record_id, "Analysis")
    deps.firestore_svc.key_moments_collection.document(record_id).update(
        {"archived": True}
    )
    return {"status": "archived"}


@router.delete("/{record_id}")
async def delete_key_moments_analysis(record_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_key_moments_analysis, record_id, "Analysis")
    deps.firestore_svc.delete_key_moments_analysis(record_id)
    return {"status": "deleted"}

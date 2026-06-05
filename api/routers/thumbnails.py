import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from helpers import (
    apply_indexed_uris,
    get_or_404,
    list_completed_production_sources,
    require_firestore,
    sign_nested_list_uris,
    sign_record_urls,
)
from models import ThumbnailRecord, ThumbnailScreenshot
from routers._crud import register_crud_routes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/thumbnails", tags=["thumbnails"])


def _sign(record: ThumbnailRecord) -> dict:
    """Sign top-level video/thumbnail URIs plus per-screenshot URIs."""
    data = sign_record_urls(
        record,
        {
            "video_gcs_uri": "video_signed_url",
            "thumbnail_gcs_uri": "thumbnail_signed_url",
        },
        lambda cache: deps.firestore_svc.update_thumbnail_record(
            record.id, {"signed_urls": cache}
        ),
    )
    sign_nested_list_uris(data, "screenshots")
    return data


register_crud_routes(
    router,
    resource_label="Thumbnail record",
    getter=lambda rid: deps.firestore_svc.get_thumbnail_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_thumbnail_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_thumbnail_record(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_thumbnail_records(
        include_archived=include_archived
    ),
    sign_one=_sign,
)


# Feature-specific endpoints


@router.get("/sources/productions")
async def list_thumbnail_production_sources():
    return list_completed_production_sources(extra_fields={"type": "type"})


@router.post("/analyze")
async def analyze_video_for_thumbnails(request: Request, body: dict):
    if not deps.ai_svc or not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    gcs_uri = body.get("gcs_uri")
    prompt_id = body.get("prompt_id")
    logger.info(
        "thumbnails/analyze request: source=%s mime=%s prompt_id=%s gcs_uri=%r",
        body.get("video_source"),
        body.get("mime_type"),
        prompt_id,
        gcs_uri,
    )
    if not gcs_uri or not prompt_id:
        raise HTTPException(
            status_code=400, detail="gcs_uri and prompt_id are required"
        )
    if not gcs_uri.startswith("gs://"):
        # Guard against a non-video reference (e.g. a production ID) reaching
        # the model, which returns an opaque 500 INTERNAL instead of a 400.
        raise HTTPException(
            status_code=400,
            detail=f"gcs_uri must be a gs:// video URI, got: {gcs_uri!r}",
        )
    try:
        result = await deps.ai_svc.analyze_video_for_thumbnails(
            gcs_uri=gcs_uri,
            mime_type=body.get("mime_type", "video/mp4"),
            prompt_id=prompt_id,
            model_id=body.get("model_id"),
            region=body.get("region"),
        )
    except Exception as e:
        logger.error(f"Thumbnail analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    analysis_data = result.data if hasattr(result, "data") else result.get("data")
    moments = analysis_data.get("key_moments", []) if analysis_data else []
    screenshots = [
        ThumbnailScreenshot(
            timestamp=f"{m.get('timestamp_start', '0:00')}-{m.get('timestamp_end', '0:00')}",
            title=m.get("title", ""),
            description=m.get("description", ""),
            visual_characteristics=m.get("visual_characteristics", ""),
            category=m.get("category"),
            tags=m.get("tags", []),
        )
        for m in moments
    ]
    record = ThumbnailRecord(
        video_gcs_uri=gcs_uri,
        video_filename=body.get("video_filename", ""),
        video_source=body.get("video_source", "upload"),
        production_id=body.get("production_id"),
        mime_type=body.get("mime_type", "video/mp4"),
        analysis_prompt_id=prompt_id,
        invite_code=getattr(request.state, "invite_code", None),
        video_summary=analysis_data.get("video_summary") if analysis_data else None,
        screenshots=screenshots,
        status="screenshots_ready",
        usage=result.usage if hasattr(result, "usage") else result.get("usage", {}),
    )
    deps.firestore_svc.create_thumbnail_record(record)
    return {"id": record.id, "data": analysis_data, "usage": record.usage.dict()}


@router.post("/{record_id}/screenshots")
async def save_thumbnail_screenshots(record_id: str, request: dict):
    require_firestore()
    record = get_or_404(
        deps.firestore_svc.get_thumbnail_record, record_id, "Thumbnail record"
    )
    updated_screenshots = apply_indexed_uris(
        [s.dict() for s in record.screenshots], request.get("screenshots", [])
    )
    deps.firestore_svc.update_thumbnail_record(
        record_id,
        {"screenshots": updated_screenshots, "status": "screenshots_ready"},
    )
    return {"status": "screenshots_saved"}


@router.post("/{record_id}/collage")
async def generate_thumbnail_collage(request: Request, record_id: str, body: dict):
    if not deps.ai_svc or not deps.firestore_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = get_or_404(
        deps.firestore_svc.get_thumbnail_record, record_id, "Thumbnail record"
    )
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id is required")
    screenshot_uris = [s.gcs_uri for s in record.screenshots if s.gcs_uri]
    if not screenshot_uris:
        raise HTTPException(
            status_code=400, detail="No screenshots with GCS URIs found"
        )
    deps.firestore_svc.update_thumbnail_record(
        record_id, {"status": "generating", "collage_prompt_id": prompt_id}
    )
    try:
        result = await deps.ai_svc.generate_thumbnail_collage(
            screenshot_uris=screenshot_uris,
            prompt_id=prompt_id,
        )
    except Exception as e:
        logger.error(f"Collage generation failed: {e}")
        deps.firestore_svc.update_thumbnail_record(
            record_id, {"status": "screenshots_ready"}
        )
        raise HTTPException(status_code=500, detail=str(e))
    thumbnail_gcs_uri = result.data.get("image_url")
    signed_url = (
        deps.storage_svc.get_signed_url(thumbnail_gcs_uri)
        if thumbnail_gcs_uri
        else None
    )
    deps.firestore_svc.update_thumbnail_record(
        record_id,
        {"thumbnail_gcs_uri": thumbnail_gcs_uri, "status": "completed"},
    )
    return {
        "thumbnail_gcs_uri": thumbnail_gcs_uri,
        "thumbnail_signed_url": signed_url,
    }

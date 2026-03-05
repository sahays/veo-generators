import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from models import KeyMomentsRecord, ProjectStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/key-moments", tags=["key-moments"])


def _sign_key_moments_url(record: KeyMomentsRecord) -> dict:
    """Return record dict with a signed video URL."""
    data = record.dict()
    if not deps.storage_svc or not record.video_gcs_uri:
        return data
    cache = data.get("signed_urls") or {}
    url, changed = deps.storage_svc.resolve_cached_url(record.video_gcs_uri, cache)
    data["video_signed_url"] = url
    if changed and deps.firestore_svc:
        deps.firestore_svc.key_moments_collection.document(record.id).update(
            {"signed_urls": cache}
        )
    data.pop("signed_urls", None)
    return data


@router.get("")
async def list_key_moments(
    request: Request, archived: bool = False, mine: bool = False
):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    records = deps.firestore_svc.get_key_moments_analyses(include_archived=archived)
    if mine:
        code = getattr(request.state, "invite_code", None)
        records = [r for r in records if r.invite_code == code]
    return [_sign_key_moments_url(r) for r in records]


@router.get("/sources/productions")
async def list_production_sources():
    """List completed productions with signed final video URLs."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    productions = deps.firestore_svc.get_productions()
    completed = [
        p
        for p in productions
        if p.status == ProjectStatus.COMPLETED and p.final_video_url
    ]
    results = []
    for p in completed:
        signed_url = ""
        if deps.storage_svc and p.final_video_url:
            if p.final_video_url.startswith("gs://"):
                signed_url = deps.storage_svc.get_signed_url(p.final_video_url)
            else:
                signed_url = p.final_video_url
        results.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "final_video_url": p.final_video_url,
                "video_signed_url": signed_url,
                "createdAt": p.createdAt.isoformat() if p.createdAt else None,
            }
        )
    return results


@router.get("/{record_id}")
async def get_key_moments_analysis(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
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


@router.post("/{record_id}/archive")
async def archive_key_moments_analysis(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    deps.firestore_svc.key_moments_collection.document(record_id).update(
        {"archived": True}
    )
    return {"status": "archived"}


@router.delete("/{record_id}")
async def delete_key_moments_analysis(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    deps.firestore_svc.delete_key_moments_analysis(record_id)
    return {"status": "deleted"}

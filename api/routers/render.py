"""Production render endpoints — start render, kick off stitch, poll stitch status.

Pipeline state machine lives in `routers.render_helpers`.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import deps
from models import ProjectStatus
from routers.render_helpers import process_render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["render"])


def _require_render_services() -> None:
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def _require_stitch_services() -> None:
    if not deps.firestore_svc or not deps.transcoder_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def _require_production(production_id: str):
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        raise HTTPException(status_code=404)
    return production


@router.post("/{id}/render")
async def start_render(request: Request, id: str, background_tasks: BackgroundTasks):
    _require_render_services()
    production = _require_production(id)
    # Don't restart if already running.
    if production.status in (ProjectStatus.GENERATING, ProjectStatus.STITCHING):
        return {"status": str(production.status.value)}
    deps.firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_render, id)
    return {"status": "started"}


def _scene_uris_or_400(production) -> list[str]:
    uris: list[str] = []
    for scene in production.scenes:
        if not scene.video_url or not scene.video_url.startswith("gs://"):
            raise HTTPException(
                status_code=400, detail=f"Scene {scene.id} does not have a video yet"
            )
        uris.append(scene.video_url)
    return uris


@router.post("/{id}/stitch")
async def stitch_production(request: Request, id: str):
    """Stitch all completed scene videos into a final video."""
    _require_stitch_services()
    production = _require_production(id)
    scene_uris = _scene_uris_or_400(production)

    deps.firestore_svc.update_production(id, {"status": ProjectStatus.STITCHING})
    try:
        job_name, final_uri = deps.transcoder_svc.stitch_from_uris(
            id, scene_uris, orientation=production.orientation
        )
        deps.firestore_svc.update_production(
            id, {"stitch_job_name": job_name, "final_video_url": final_uri}
        )
        return {"status": "stitching", "job_name": job_name}
    except Exception as e:
        logger.error(f"Stitching failed: {e}")
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))


def _stitch_status_response(production_id: str, production, job_state: str) -> dict:
    if job_state == "SUCCEEDED":
        deps.firestore_svc.update_production(
            production_id, {"status": ProjectStatus.COMPLETED}
        )
        signed_url = (
            deps.storage_svc.get_signed_url(production.final_video_url)
            if production.final_video_url
            else None
        )
        return {"status": "completed", "final_video_url": signed_url}
    if job_state in ("FAILED", "UNKNOWN"):
        deps.firestore_svc.update_production(
            production_id,
            {
                "status": ProjectStatus.FAILED,
                "error_message": f"Transcoder job {job_state}",
            },
        )
        return {"status": "failed", "error": f"Transcoder job {job_state}"}
    return {"status": "stitching", "job_state": job_state}


@router.get("/{id}/stitch-status")
async def get_stitch_status(id: str):
    """Check the status of a running stitch (Transcoder) job."""
    _require_stitch_services()
    production = _require_production(id)
    if not production.stitch_job_name:
        return {"status": str(production.status.value)}
    job_state = deps.transcoder_svc.get_job_status(production.stitch_job_name)
    return _stitch_status_response(id, production, job_state)

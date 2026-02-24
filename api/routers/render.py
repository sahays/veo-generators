import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import deps
from models import ProjectStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["render"])


async def process_render_kickoff(production_id: str):
    """Fire off non-blocking video generation for all scenes that need it.

    Each scene gets its Veo operation started and the operation_name saved.
    The client polls each operation via the diagnostics endpoint, which
    persists results back to Firestore when complete.
    """
    if not deps.firestore_svc or not deps.video_svc:
        return
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return

    try:
        for scene in production.scenes:
            if scene.video_url and scene.video_url.startswith("gs://"):
                logger.info(f"Scene {scene.id} already has video, skipping")
                if scene.status != "completed":
                    deps.firestore_svc.update_scene(
                        production_id, scene.id, {"status": "completed"}
                    )
                continue

            deps.firestore_svc.update_scene(
                production_id, scene.id, {"status": "generating"}
            )
            result = await deps.video_svc.generate_scene_video(
                production_id, scene, blocking=False, project=production
            )
            if isinstance(result, dict):
                scene_updates = {}
                if result.get("operation_name"):
                    scene_updates["operation_name"] = result["operation_name"]
                if result.get("generated_prompt"):
                    scene_updates["generated_prompt"] = result["generated_prompt"]
                    scene_updates["video_prompt"] = result["generated_prompt"]
                if scene_updates:
                    deps.firestore_svc.update_scene(
                        production_id, scene.id, scene_updates
                    )
    except Exception as e:
        logger.error(f"Render kickoff failed: {e}")
        deps.firestore_svc.update_production(
            production_id,
            {"status": ProjectStatus.FAILED, "error_message": str(e)},
        )


@router.post("/{id}/render")
@deps.limiter.limit("10/minute")
async def start_render(request: Request, id: str, background_tasks: BackgroundTasks):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    deps.firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_render_kickoff, id)
    return {"status": "started"}


@router.post("/{id}/stitch")
@deps.limiter.limit("10/minute")
async def stitch_production(request: Request, id: str):
    """Stitch all completed scene videos into a final video.

    Called by the client once all scenes have video_url populated.
    """
    if not deps.firestore_svc or not deps.transcoder_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene_uris = []
    for scene in production.scenes:
        if not scene.video_url or not scene.video_url.startswith("gs://"):
            raise HTTPException(
                status_code=400,
                detail=f"Scene {scene.id} does not have a video yet",
            )
        scene_uris.append(scene.video_url)

    deps.firestore_svc.update_production(id, {"status": ProjectStatus.STITCHING})
    try:
        job_name, final_uri = deps.transcoder_svc.stitch_from_uris(
            id, scene_uris, orientation=production.orientation
        )
        deps.firestore_svc.update_production(
            id,
            {
                "stitch_job_name": job_name,
                "final_video_url": final_uri,
            },
        )
        return {"status": "stitching", "job_name": job_name}
    except Exception as e:
        logger.error(f"Stitching failed: {e}")
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/stitch-status")
async def get_stitch_status(id: str):
    """Check the status of a running stitch (Transcoder) job."""
    if not deps.firestore_svc or not deps.transcoder_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    if not production.stitch_job_name:
        return {"status": str(production.status.value)}

    job_state = deps.transcoder_svc.get_job_status(production.stitch_job_name)

    if job_state == "SUCCEEDED":
        deps.firestore_svc.update_production(id, {"status": ProjectStatus.COMPLETED})
        signed_url = (
            deps.storage_svc.get_signed_url(production.final_video_url)
            if production.final_video_url
            else None
        )
        return {
            "status": "completed",
            "final_video_url": signed_url,
        }
    elif job_state in ("FAILED", "UNKNOWN"):
        deps.firestore_svc.update_production(
            id,
            {
                "status": ProjectStatus.FAILED,
                "error_message": f"Transcoder job {job_state}",
            },
        )
        return {"status": "failed", "error": f"Transcoder job {job_state}"}
    else:
        return {"status": "stitching", "job_state": job_state}

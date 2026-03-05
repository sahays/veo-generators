import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import deps
from helpers import accumulate_image_cost, accumulate_veo_cost, parse_timestamp
from models import ProjectStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["render"])

VEO_COST_PER_SECOND = 0.40  # Veo 3.1 Standard


async def _poll_veo_operation(operation_name: str, timeout: int = 600) -> dict:
    """Poll a Veo operation until done or timeout (seconds)."""
    elapsed = 0
    interval = 10
    while elapsed < timeout:
        status = await deps.video_svc.get_video_generation_status(operation_name)
        if status.get("status") in ("completed", "failed", "error"):
            return status
        await asyncio.sleep(interval)
        elapsed += interval
    return {"status": "failed", "error": "Operation timed out"}


async def process_render(production_id: str):
    """Sequential state machine: frame -> video per scene, then stitch.

    All state is persisted to Firestore so the frontend can poll GET /productions/{id}.
    """
    if not deps.firestore_svc or not deps.ai_svc or not deps.video_svc:
        return

    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return

    try:
        for scene in production.scenes:
            # Skip scenes that already have video
            if scene.video_url and scene.video_url.startswith("gs://"):
                logger.info(f"Scene {scene.id} already has video, skipping")
                if scene.status != "completed":
                    deps.firestore_svc.update_scene(
                        production_id, scene.id, {"status": "completed"}
                    )
                continue

            # --- Step 1: Generate frame (image) ---
            if not scene.thumbnail_url or not scene.thumbnail_url.startswith("gs://"):
                deps.firestore_svc.update_scene(
                    production_id, scene.id, {"status": "generating_frame"}
                )
                try:
                    frame_result = await deps.ai_svc.generate_frame(
                        production_id,
                        scene,
                        production.orientation,
                        project=production,
                    )
                    gcs_uri = frame_result.data["image_url"]
                    scene_updates = {"thumbnail_url": gcs_uri}
                    if frame_result.data.get("generated_prompt"):
                        scene_updates["generated_prompt"] = frame_result.data[
                            "generated_prompt"
                        ]
                        scene_updates["image_prompt"] = frame_result.data[
                            "generated_prompt"
                        ]
                    deps.firestore_svc.update_scene(
                        production_id, scene.id, scene_updates
                    )
                    accumulate_image_cost(production_id, frame_result.usage.cost_usd)
                    # Update scene object for video step (needs thumbnail_url)
                    scene.thumbnail_url = gcs_uri
                except Exception as e:
                    logger.error(f"Frame generation failed for scene {scene.id}: {e}")
                    deps.firestore_svc.update_scene(
                        production_id,
                        scene.id,
                        {"status": "failed", "error_message": str(e)},
                    )
                    deps.firestore_svc.update_production(
                        production_id,
                        {
                            "status": ProjectStatus.FAILED,
                            "error_message": f"Frame gen failed for {scene.id}: {e}",
                        },
                    )
                    return

            # --- Step 2: Generate video ---
            deps.firestore_svc.update_scene(
                production_id, scene.id, {"status": "generating"}
            )
            try:
                result = await deps.video_svc.generate_scene_video(
                    production_id, scene, blocking=False, project=production
                )
            except Exception as e:
                logger.error(f"Video generation failed for scene {scene.id}: {e}")
                deps.firestore_svc.update_scene(
                    production_id,
                    scene.id,
                    {"status": "failed", "error_message": str(e)},
                )
                deps.firestore_svc.update_production(
                    production_id,
                    {
                        "status": ProjectStatus.FAILED,
                        "error_message": f"Video gen failed for {scene.id}: {e}",
                    },
                )
                return

            if not isinstance(result, dict):
                continue

            # Save operation name and prompt
            scene_updates = {}
            if result.get("operation_name"):
                scene_updates["operation_name"] = result["operation_name"]
            if result.get("generated_prompt"):
                scene_updates["generated_prompt"] = result["generated_prompt"]
                scene_updates["video_prompt"] = result["generated_prompt"]
            if scene_updates:
                deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)

            # Poll Veo operation to completion
            op_name = result.get("operation_name")
            if op_name:
                veo_status = await _poll_veo_operation(op_name)
                if veo_status.get("status") == "completed" and veo_status.get(
                    "video_uri"
                ):
                    deps.firestore_svc.update_scene(
                        production_id,
                        scene.id,
                        {
                            "status": "completed",
                            "video_url": veo_status["video_uri"],
                        },
                    )
                    # Track Veo cost
                    try:
                        veo_start = parse_timestamp(scene.timestamp_start)
                        veo_end = parse_timestamp(scene.timestamp_end)
                        veo_duration = max(4, min(8, int(veo_end - veo_start)))
                    except (ValueError, IndexError):
                        veo_duration = 8
                    accumulate_veo_cost(
                        production_id, veo_duration, VEO_COST_PER_SECOND
                    )
                else:
                    error_msg = veo_status.get("error") or veo_status.get(
                        "message", "Video generation failed"
                    )
                    logger.error(f"Veo failed for scene {scene.id}: {error_msg}")
                    deps.firestore_svc.update_scene(
                        production_id,
                        scene.id,
                        {"status": "failed", "error_message": str(error_msg)},
                    )
                    deps.firestore_svc.update_production(
                        production_id,
                        {
                            "status": ProjectStatus.FAILED,
                            "error_message": f"Video failed for {scene.id}: {error_msg}",
                        },
                    )
                    return

        # --- Step 3: Stitch ---
        # Re-read production to get updated scene video URLs
        production = deps.firestore_svc.get_production(production_id)
        if not production:
            return

        scene_uris = []
        for scene in production.scenes:
            if not scene.video_url or not scene.video_url.startswith("gs://"):
                logger.error(f"Scene {scene.id} missing video after render loop")
                deps.firestore_svc.update_production(
                    production_id,
                    {
                        "status": ProjectStatus.FAILED,
                        "error_message": f"Scene {scene.id} missing video",
                    },
                )
                return
            scene_uris.append(scene.video_url)

        if not deps.transcoder_svc:
            logger.error("Transcoder service not available")
            return

        deps.firestore_svc.update_production(
            production_id, {"status": ProjectStatus.STITCHING}
        )
        job_name, final_uri = deps.transcoder_svc.stitch_from_uris(
            production_id, scene_uris, orientation=production.orientation
        )
        deps.firestore_svc.update_production(
            production_id,
            {"stitch_job_name": job_name, "final_video_url": final_uri},
        )

        # Poll stitch job
        while True:
            await asyncio.sleep(10)
            job_state = deps.transcoder_svc.get_job_status(job_name)
            if job_state == "SUCCEEDED":
                deps.firestore_svc.update_production(
                    production_id, {"status": ProjectStatus.COMPLETED}
                )
                logger.info(f"Production {production_id} completed successfully")
                return
            elif job_state in ("FAILED", "UNKNOWN"):
                deps.firestore_svc.update_production(
                    production_id,
                    {
                        "status": ProjectStatus.FAILED,
                        "error_message": f"Transcoder job {job_state}",
                    },
                )
                return

    except Exception as e:
        logger.error(f"Render failed for {production_id}: {e}")
        deps.firestore_svc.update_production(
            production_id,
            {"status": ProjectStatus.FAILED, "error_message": str(e)},
        )


@router.post("/{id}/render")
async def start_render(request: Request, id: str, background_tasks: BackgroundTasks):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    # Don't restart if already running
    if production.status in (
        ProjectStatus.GENERATING,
        ProjectStatus.STITCHING,
    ):
        return {"status": str(production.status.value)}
    deps.firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_render, id)
    return {"status": "started"}


@router.post("/{id}/stitch")
async def stitch_production(request: Request, id: str):
    """Stitch all completed scene videos into a final video."""
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

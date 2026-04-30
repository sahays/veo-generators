"""Render state machine — frame → video → stitch, one scene at a time.

Split out of `routers/render.py` so the router stays focused on the three
HTTP endpoints. All state is persisted to Firestore so the frontend can
poll GET /productions/{id} regardless of where in the pipeline we are.
"""

import asyncio
import logging

import deps
from cost_tracking import (
    accumulate_image_cost_on,
    accumulate_transcoder_cost,
    accumulate_veo_cost_on,
)
from helpers import parse_timestamp
from models import ProjectStatus
from pricing_config import DEFAULT_VIDEO_MODEL

logger = logging.getLogger(__name__)


def _scene_duration_seconds(scene) -> int:
    """Veo billing duration: clipped into [4, 8]; defaults to 8 on parse error."""
    try:
        start = parse_timestamp(scene.timestamp_start)
        end = parse_timestamp(scene.timestamp_end)
        return max(4, min(8, int(end - start)))
    except (ValueError, IndexError):
        return 8


def _fail_production(production_id: str, error_message: str) -> None:
    deps.firestore_svc.update_production(
        production_id,
        {"status": ProjectStatus.FAILED, "error_message": error_message},
    )


def _fail_scene(production_id: str, scene_id: str, error: Exception | str) -> None:
    deps.firestore_svc.update_scene(
        production_id,
        scene_id,
        {"status": "failed", "error_message": str(error)},
    )


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


def _record_frame_result(production_id: str, scene, frame_result) -> None:
    """Persist the frame URI + accumulate image cost; mutate the scene object
    so the video step downstream sees the new thumbnail_url."""
    gcs_uri = frame_result.data["image_url"]
    scene_updates = {"thumbnail_url": gcs_uri}
    if frame_result.data.get("generated_prompt"):
        scene_updates["generated_prompt"] = frame_result.data["generated_prompt"]
        scene_updates["image_prompt"] = frame_result.data["generated_prompt"]
    deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)
    accumulate_image_cost_on(
        "production",
        production_id,
        frame_result.usage.cost_usd,
        input_tokens=frame_result.usage.image_input_tokens,
        output_tokens=frame_result.usage.image_output_tokens,
        model_name=frame_result.usage.image_model_name,
    )
    scene.thumbnail_url = gcs_uri


async def _generate_scene_frame(production_id: str, scene, production) -> bool:
    """Generate a frame/image for a single scene. Returns True on success."""
    if scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
        return True

    deps.firestore_svc.update_scene(
        production_id, scene.id, {"status": "generating_frame"}
    )
    try:
        frame_result = await deps.ai_svc.generate_frame(
            production_id, scene, production.orientation, project=production
        )
    except Exception as e:
        logger.error(f"Frame generation failed for scene {scene.id}: {e}")
        _fail_scene(production_id, scene.id, e)
        _fail_production(production_id, f"Frame gen failed for {scene.id}: {e}")
        return False

    _record_frame_result(production_id, scene, frame_result)
    return True


def _persist_video_result(production_id: str, scene, result: dict) -> None:
    scene_updates: dict = {}
    if result.get("operation_name"):
        scene_updates["operation_name"] = result["operation_name"]
    if result.get("generated_prompt"):
        scene_updates["generated_prompt"] = result["generated_prompt"]
        scene_updates["video_prompt"] = result["generated_prompt"]
    if scene_updates:
        deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)
    # Stash resolved video model on the scene object so _poll_scene_video
    # can cost-account with the correct rate.
    if result.get("model_id"):
        scene._video_model_id = result["model_id"]


async def _generate_scene_video(production_id: str, scene, production):
    """Kick off video generation for a single scene. Returns the result dict
    (or a non-dict for already-generated scenes), or None on failure."""
    deps.firestore_svc.update_scene(production_id, scene.id, {"status": "generating"})
    try:
        result = await deps.video_svc.generate_scene_video(
            production_id, scene, blocking=False, project=production
        )
    except Exception as e:
        logger.error(f"Video generation failed for scene {scene.id}: {e}")
        _fail_scene(production_id, scene.id, e)
        _fail_production(production_id, f"Video gen failed for {scene.id}: {e}")
        return None

    if isinstance(result, dict):
        _persist_video_result(production_id, scene, result)
    return result


async def _poll_scene_video(production_id: str, scene) -> bool:
    """Poll a scene's Veo operation until complete. Returns True on success."""
    op_name = getattr(scene, "_pending_op", None)
    if not op_name:
        return True

    veo_status = await _poll_veo_operation(op_name)
    if veo_status.get("status") == "completed" and veo_status.get("video_uri"):
        deps.firestore_svc.update_scene(
            production_id,
            scene.id,
            {"status": "completed", "video_url": veo_status["video_uri"]},
        )
        model_id = getattr(scene, "_video_model_id", None) or DEFAULT_VIDEO_MODEL
        accumulate_veo_cost_on(
            "production", production_id, _scene_duration_seconds(scene), model_id
        )
        return True

    error = veo_status.get("error") or veo_status.get("message", "Video generation failed")
    logger.error(f"Veo failed for scene {scene.id}: {error}")
    _fail_scene(production_id, scene.id, error)
    _fail_production(production_id, f"Video failed for {scene.id}: {error}")
    return False


def _collect_scene_uris(production_id: str, production) -> list[str] | None:
    """Single pass: validate every scene has a GCS video, accumulate URIs.
    Returns None and marks the production failed on the first missing video."""
    uris: list[str] = []
    for scene in production.scenes:
        if not scene.video_url or not scene.video_url.startswith("gs://"):
            logger.error(f"Scene {scene.id} missing video after render loop")
            _fail_production(production_id, f"Scene {scene.id} missing video")
            return None
        uris.append(scene.video_url)
    return uris


async def _wait_for_stitch(
    production_id: str, production, job_name: str, interval: int = 10
) -> None:
    """Poll the transcoder job until it terminates; record the outcome."""
    while True:
        await asyncio.sleep(interval)
        state = deps.transcoder_svc.get_job_status(job_name)
        if state == "SUCCEEDED":
            deps.firestore_svc.update_production(
                production_id, {"status": ProjectStatus.COMPLETED}
            )
            total_seconds = sum(_scene_duration_seconds(s) for s in production.scenes)
            accumulate_transcoder_cost(
                "production", production_id, total_seconds / 60.0
            )
            logger.info(f"Production {production_id} completed successfully")
            return
        if state in ("FAILED", "UNKNOWN"):
            _fail_production(production_id, f"Transcoder job {state}")
            return


async def _stitch_production(production_id: str, production) -> None:
    """Stitch all scene videos into a final video and poll until done."""
    scene_uris = _collect_scene_uris(production_id, production)
    if scene_uris is None:
        return
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
        production_id, {"stitch_job_name": job_name, "final_video_url": final_uri}
    )
    await _wait_for_stitch(production_id, production, job_name)


async def _process_one_scene(production_id: str, scene, production) -> bool:
    """Run frame → video → poll for a single scene. Returns False if the
    pipeline should abort (a failure already marked the production failed)."""
    if scene.video_url and scene.video_url.startswith("gs://"):
        if scene.status != "completed":
            deps.firestore_svc.update_scene(
                production_id, scene.id, {"status": "completed"}
            )
        return True

    if not await _generate_scene_frame(production_id, scene, production):
        return False

    result = await _generate_scene_video(production_id, scene, production)
    if result is None:
        return False
    if not isinstance(result, dict):
        return True

    op_name = result.get("operation_name")
    if op_name:
        scene._pending_op = op_name
        return await _poll_scene_video(production_id, scene)
    return True


async def process_render(production_id: str) -> None:
    """Sequential state machine: frame → video per scene, then stitch."""
    if not deps.firestore_svc or not deps.ai_svc or not deps.video_svc:
        return
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return

    try:
        for scene in production.scenes:
            if not await _process_one_scene(production_id, scene, production):
                return

        production = deps.firestore_svc.get_production(production_id)
        if production:
            await _stitch_production(production_id, production)
    except Exception as e:
        logger.error(f"Render failed for {production_id}: {e}")
        _fail_production(production_id, str(e))

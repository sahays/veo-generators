import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from cost_tracking import accumulate_image_cost_on, accumulate_veo_cost_on
from helpers import (
    build_prompt_data,
    build_flat_image_prompt,
    build_flat_video_prompt,
    parse_timestamp,
)
from models import AIResponseWrapper, ProjectStatus
from pricing_config import DEFAULT_VIDEO_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["scenes"])


@router.post("/{id}/scenes/{scene_id}/build-prompt")
async def build_scene_prompt(id: str, scene_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)
    return build_prompt_data(scene, production)


@router.patch("/{id}/scenes/{scene_id}")
async def update_scene(id: str, scene_id: str, updates: dict):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    ALLOWED = {
        "visual_description",
        "narration",
        "narration_enabled",
        "music_description",
        "music_enabled",
    }
    filtered = {k: v for k, v in updates.items() if k in ALLOWED}
    if filtered:
        deps.firestore_svc.update_scene(id, scene_id, filtered)
    return {"ok": True}


@router.post(
    "/{id}/scenes/{scene_id}/frame",
    response_model=AIResponseWrapper,
)
async def generate_scene_frame(
    request: Request, id: str, scene_id: str, body: dict = {}
):
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    prompt_override = None
    prompt_data = body.get("prompt_data") if body else None
    if prompt_data:
        prompt_override = build_flat_image_prompt(prompt_data)
        new_desc = prompt_data.get("visual_description")
        if new_desc and new_desc != scene.visual_description:
            deps.firestore_svc.update_scene(
                id, scene_id, {"visual_description": new_desc}
            )

    frame_model_id = body.get("model_id") if body else None
    frame_region = body.get("region") if body else None
    try:
        result = await deps.ai_svc.generate_frame(
            id,
            scene,
            production.orientation,
            project=production,
            prompt_override=prompt_override,
            model_id=frame_model_id,
            region=frame_region,
        )
    except Exception as e:
        logger.error(f"Frame generation failed for scene {scene_id}: {e}")
        error_msg = f"Image generation failed for scene {scene_id}: {e}"
        deps.firestore_svc.update_scene(
            id, scene_id, {"status": "failed", "error_message": str(e)}
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
        )
        raise HTTPException(status_code=500, detail=error_msg)

    gcs_uri = result.data["image_url"]
    scene_updates = {"thumbnail_url": gcs_uri}
    if result.data.get("generated_prompt"):
        scene_updates["generated_prompt"] = result.data["generated_prompt"]
        scene_updates["image_prompt"] = result.data["generated_prompt"]
    deps.firestore_svc.update_scene(id, scene_id, scene_updates)
    accumulate_image_cost_on(
        "production",
        id,
        result.usage.cost_usd,
        input_tokens=result.usage.image_input_tokens,
        output_tokens=result.usage.image_output_tokens,
        model_name=result.usage.image_model_name,
    )
    # Return signed URL for immediate display
    result.data["image_url"] = deps.storage_svc.get_signed_url(gcs_uri)
    return result


@router.post("/{id}/scenes/{scene_id}/video")
async def generate_scene_video(
    request: Request, id: str, scene_id: str, body: dict = {}
):
    if not deps.firestore_svc or not deps.video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    prompt_override = None
    prompt_data = body.get("prompt_data") if body else None
    if prompt_data:
        prompt_override = build_flat_video_prompt(prompt_data)
        new_desc = prompt_data.get("visual_description")
        if new_desc and new_desc != scene.visual_description:
            deps.firestore_svc.update_scene(
                id, scene_id, {"visual_description": new_desc}
            )

    video_model_id = body.get("model_id") if body else None
    video_region = body.get("region") if body else None
    deps.firestore_svc.update_scene(id, scene_id, {"status": "generating"})
    try:
        result = await deps.video_svc.generate_scene_video(
            id,
            scene,
            blocking=False,
            project=production,
            prompt_override=prompt_override,
            model_id=video_model_id,
            region=video_region,
        )
    except Exception as e:
        logger.error(f"Video generation failed for scene {scene_id}: {e}")
        error_msg = f"Video generation failed for scene {scene_id}: {e}"
        deps.firestore_svc.update_scene(
            id, scene_id, {"status": "failed", "error_message": str(e)}
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
        )
        raise HTTPException(status_code=500, detail=error_msg)

    # Resolve actual Veo model from the result (video_service reports what it used)
    resolved_video_model = (
        (result.get("model_id") if isinstance(result, dict) else None)
        or video_model_id
        or DEFAULT_VIDEO_MODEL
    )
    reported_duration = (
        result.get("duration_seconds") if isinstance(result, dict) else None
    )
    try:
        veo_start = parse_timestamp(scene.timestamp_start)
        veo_end = parse_timestamp(scene.timestamp_end)
        veo_duration = max(4, min(8, int(veo_end - veo_start)))
    except (ValueError, IndexError):
        veo_duration = 8
    accumulate_veo_cost_on(
        "production",
        id,
        reported_duration or veo_duration,
        resolved_video_model,
    )

    if isinstance(result, dict) and "operation_name" in result:
        if result.get("generated_prompt"):
            deps.firestore_svc.update_scene(
                id,
                scene_id,
                {
                    "generated_prompt": result["generated_prompt"],
                    "video_prompt": result["generated_prompt"],
                },
            )
        return {"operation_name": result["operation_name"], "status": "processing"}

    # Blocking result
    if isinstance(result, dict) and result.get("video_uri"):
        scene_updates = {
            "status": "completed",
            "video_url": result["video_uri"],
        }
        if result.get("generated_prompt"):
            scene_updates["generated_prompt"] = result["generated_prompt"]
            scene_updates["video_prompt"] = result["generated_prompt"]
        deps.firestore_svc.update_scene(id, scene_id, scene_updates)
        signed_url = (
            deps.storage_svc.get_signed_url(result["video_uri"])
            if deps.storage_svc
            else None
        )
        return {
            "status": "completed",
            "video_uri": result["video_uri"],
            "signed_url": signed_url,
        }

    error_msg = f"Video generation failed for scene {scene_id}"
    deps.firestore_svc.update_scene(
        id, scene_id, {"status": "failed", "error_message": error_msg}
    )
    deps.firestore_svc.update_production(
        id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
    )
    return {"status": "failed", "error_message": error_msg}

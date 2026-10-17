"""Scene-level prompt building, frame generation, and video generation endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from cost_tracking import accumulate_image_cost_on, accumulate_veo_cost_on
import deps
from helpers import (
    build_flat_image_prompt,
    build_flat_video_prompt,
    build_prompt_data,
    parse_timestamp,
)
from models import AIResponseWrapper, Project, ProjectStatus, Scene
from pricing_config import DEFAULT_VIDEO_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["scenes"])


def _scene_log(
    where: str, what: str, why: str, how: str = "scenes_router"
) -> dict[str, str]:
    """Build structured 5W1H telemetry context for scene routes."""
    return {
        "who": "scenes_router",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


def _get_production_and_scene(id: str, scene_id: str) -> tuple[Project, Scene]:
    """Fetch a production and target scene or raise 404."""
    production = deps.firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)
    return production, scene


@router.post("/{id}/scenes/{scene_id}/build-prompt")
async def build_scene_prompt(id: str, scene_id: str) -> dict[str, Any]:
    """Construct structured prompt data for a single scene."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production, scene = _get_production_and_scene(id, scene_id)
    return build_prompt_data(scene, production)


@router.patch("/{id}/scenes/{scene_id}")
async def update_scene(
    id: str, scene_id: str, updates: dict[str, Any]
) -> dict[str, bool]:
    """Update editable fields on a single scene."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    _get_production_and_scene(id, scene_id)
    allowed = {
        "visual_description",
        "narration",
        "narration_enabled",
        "music_description",
        "music_enabled",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if filtered:
        deps.firestore_svc.update_scene(id, scene_id, filtered)
    return {"ok": True}


def _extract_prompt_override(
    id: str, scene: Scene, body: dict[str, Any], builder_fn: Any
) -> str | None:
    """Build prompt override from `body['prompt_data']` and sync `visual_description`."""
    prompt_data = body.get("prompt_data") if body else None
    if not prompt_data:
        return None
    prompt_override = builder_fn(prompt_data)
    new_desc = prompt_data.get("visual_description")
    if new_desc and new_desc != scene.visual_description:
        deps.firestore_svc.update_scene(id, scene.id, {"visual_description": new_desc})
        scene.visual_description = new_desc
    return prompt_override


async def _generate_start_keyframe(
    id: str,
    scene: Scene,
    production: Project,
    prompt_override: str | None,
    model_id: str | None,
    region: str | None,
) -> Any:
    """Invoke `ai_svc.generate_frame` for the start keyframe with legacy fallback."""
    try:
        try:
            return await deps.ai_svc.generate_frame(
                id,
                scene,
                production.orientation,
                project=production,
                prompt_override=prompt_override,
                model_id=model_id,
                region=region,
                frame_position="start",
            )
        except TypeError:
            return await deps.ai_svc.generate_frame(
                id,
                scene,
                production.orientation,
                project=production,
                prompt_override=prompt_override,
                model_id=model_id,
                region=region,
            )
    except Exception as e:
        logger.error(
            f"Frame generation failed for scene {scene.id}: {e}",
            extra=_scene_log("generate_scene_frame", "frame_gen_failed", str(e)),
        )
        error_msg = f"Image generation failed for scene {scene.id}: {e}"
        deps.firestore_svc.update_scene(
            id, scene.id, {"status": "failed", "error_message": str(e)}
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
        )
        raise HTTPException(status_code=500, detail=error_msg)


async def _try_generate_end_keyframe(
    id: str,
    scene: Scene,
    production: Project,
    start_gcs_uri: str,
    model_id: str | None,
    region: str | None,
    result: Any,
    scene_updates: dict[str, Any],
) -> str | None:
    """Attempt end keyframe generation and merge usage metrics into `result`."""
    try:
        end_res = await deps.ai_svc.generate_frame(
            id,
            scene,
            production.orientation,
            project=production,
            model_id=model_id,
            region=region,
            frame_position="end",
            start_frame_uri=start_gcs_uri,
        )
        end_gcs_uri = end_res.data.get("image_url")
        if not end_gcs_uri:
            return None
        scene_updates["end_frame_url"] = end_gcs_uri
        if end_res.data.get("generated_prompt"):
            scene_updates["end_frame_prompt"] = end_res.data["generated_prompt"]
            result.data["end_frame_prompt"] = end_res.data["generated_prompt"]
        eu = end_res.usage
        accumulate_image_cost_on(
            "production",
            id,
            eu.cost_usd,
            input_tokens=eu.image_input_tokens,
            output_tokens=eu.image_output_tokens,
            model_name=eu.image_model_name,
        )
        ru = result.usage
        ru.image_generations = max(1, ru.image_generations) + max(
            1, eu.image_generations
        )
        ru.image_input_tokens += eu.image_input_tokens
        ru.image_output_tokens += eu.image_output_tokens
        ru.image_cost_usd += eu.image_cost_usd
        ru.cost_usd += eu.cost_usd
        return str(end_gcs_uri)
    except Exception as e:
        logger.warning(
            f"End frame generation skipped/failed for scene {scene.id}: {e}",
            extra=_scene_log("generate_scene_frame", "end_frame_skipped", str(e)),
        )
        return None


@router.post("/{id}/scenes/{scene_id}/frame", response_model=AIResponseWrapper)
async def generate_scene_frame(
    request: Request, id: str, scene_id: str, body: dict[str, Any] = {}
) -> Any:
    """Generate start and end keyframes for a single scene."""
    _ = request
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production, scene = _get_production_and_scene(id, scene_id)
    prompt_override = _extract_prompt_override(id, scene, body, build_flat_image_prompt)
    model_id = body.get("model_id") if body else None
    region = body.get("region") if body else None
    result = await _generate_start_keyframe(
        id, scene, production, prompt_override, model_id, region
    )
    gcs_uri = result.data["image_url"]
    scene_updates: dict[str, Any] = {"thumbnail_url": gcs_uri}
    if result.data.get("generated_prompt"):
        scene_updates["generated_prompt"] = result.data["generated_prompt"]
        scene_updates["image_prompt"] = result.data["generated_prompt"]
    u = result.usage
    accumulate_image_cost_on(
        "production",
        id,
        u.cost_usd,
        input_tokens=u.image_input_tokens,
        output_tokens=u.image_output_tokens,
        model_name=u.image_model_name,
    )
    end_gcs_uri = await _try_generate_end_keyframe(
        id, scene, production, gcs_uri, model_id, region, result, scene_updates
    )
    deps.firestore_svc.update_scene(id, scene_id, scene_updates)
    result.data["image_url"] = deps.storage_svc.get_signed_url(gcs_uri)
    if end_gcs_uri:
        result.data["end_frame_url"] = deps.storage_svc.get_signed_url(end_gcs_uri)
    return result


def _record_scene_video_cost(
    id: str, scene: Scene, result: Any, video_model_id: str | None
) -> None:
    """Accumulate Veo video generation cost on the parent production."""
    resolved_model = (
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
        "production", id, reported_duration or veo_duration, resolved_model
    )


def _format_scene_video_response(id: str, scene_id: str, result: Any) -> dict[str, Any]:
    """Persist scene video state and format the endpoint response dictionary."""
    if isinstance(result, dict) and "operation_name" in result:
        if result.get("generated_prompt"):
            p_txt = result["generated_prompt"]
            deps.firestore_svc.update_scene(
                id, scene_id, {"generated_prompt": p_txt, "video_prompt": p_txt}
            )
        return {"operation_name": result["operation_name"], "status": "processing"}
    if isinstance(result, dict) and result.get("video_uri"):
        scene_updates: dict[str, Any] = {
            "status": "completed",
            "video_url": result["video_uri"],
        }
        if result.get("generated_prompt"):
            scene_updates["generated_prompt"] = result["generated_prompt"]
            scene_updates["video_prompt"] = result["generated_prompt"]
        deps.firestore_svc.update_scene(id, scene_id, scene_updates)
        signed = (
            deps.storage_svc.get_signed_url(result["video_uri"])
            if deps.storage_svc
            else None
        )
        return {
            "status": "completed",
            "video_uri": result["video_uri"],
            "signed_url": signed,
        }
    error_msg = f"Video generation failed for scene {scene_id}"
    deps.firestore_svc.update_scene(
        id, scene_id, {"status": "failed", "error_message": error_msg}
    )
    deps.firestore_svc.update_production(
        id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
    )
    return {"status": "failed", "error_message": error_msg}


@router.post("/{id}/scenes/{scene_id}/video")
async def generate_scene_video(
    request: Request, id: str, scene_id: str, body: dict[str, Any] = {}
) -> dict[str, Any]:
    """Generate a video clip for a single scene."""
    _ = request
    if not deps.firestore_svc or not deps.video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production, scene = _get_production_and_scene(id, scene_id)
    prompt_override = _extract_prompt_override(id, scene, body, build_flat_video_prompt)
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
        logger.error(
            f"Video generation failed for scene {scene_id}: {e}",
            extra=_scene_log("generate_scene_video", "video_gen_failed", str(e)),
        )
        error_msg = f"Video generation failed for scene {scene_id}: {e}"
        deps.firestore_svc.update_scene(
            id, scene_id, {"status": "failed", "error_message": str(e)}
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
        )
        raise HTTPException(status_code=500, detail=error_msg)
    _record_scene_video_cost(id, scene, result, video_model_id)
    return _format_scene_video_response(id, scene_id, result)

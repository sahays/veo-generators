"""Stage 2B: Scene video generation, Veo operation polling, and RAI retry handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import deps
from cost_tracking import accumulate_veo_cost_on
from models import UsageMetrics
from pricing_config import DEFAULT_VIDEO_MODEL, veo_rate_for
from render_pipeline.frames import _run_frame_phase_for_scene
from render_pipeline.state import (
    _fail_scene,
    _is_rai_blocked_error,
    _sanitize_scene_for_rai,
    _scene_duration_seconds,
    get_hook,
    log_extra,
)

logger = logging.getLogger(__name__)


async def _poll_veo_operation(
    operation_name: str, timeout: int = 600
) -> dict[str, Any]:
    """Poll a Veo/Omni operation until done or timeout (seconds)."""
    elapsed = 0
    interval = 10
    while elapsed < timeout:
        status = await deps.video_svc.get_video_generation_status(operation_name)
        if status.get("status") in ("completed", "failed", "error"):
            return status
        await asyncio.sleep(interval)
        elapsed += interval
    return {"status": "failed", "error": "Operation timed out"}


def _persist_video_result(
    production_id: str, scene: Any, result: dict[str, Any]
) -> None:
    """Persist operation metadata and stash model/resolution on scene."""
    scene_updates: dict[str, Any] = {}
    if result.get("operation_name"):
        scene_updates["operation_name"] = result["operation_name"]
    if result.get("generated_prompt"):
        scene_updates["generated_prompt"] = result["generated_prompt"]
        scene_updates["video_prompt"] = result["generated_prompt"]
    if scene_updates:
        deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)
    if result.get("model_id"):
        scene._video_model_id = result["model_id"]
    if result.get("resolution"):
        scene._video_resolution = result["resolution"]


async def _generate_scene_video(
    production_id: str,
    scene: Any,
    production: Any,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> Any:
    """Kick off video generation for a single scene."""
    scene._video_resolution = target_resolution
    deps.firestore_svc.update_scene(
        production_id, scene.id, {"status": "generating", "error_message": None}
    )
    try:
        try:
            result = await deps.video_svc.generate_scene_video(
                production_id,
                scene,
                blocking=False,
                project=production,
                resolution=target_resolution,
                render_quality=quality,
            )
        except TypeError:
            result = await deps.video_svc.generate_scene_video(
                production_id, scene, blocking=False, project=production
            )
    except Exception as e:
        logger.error(
            f"Video generation failed for scene {scene.id}: {e}",
            extra=log_extra(
                "_generate_scene_video", "video_gen_failed", str(e), "fail_scene"
            ),
        )
        scene._last_video_error = str(e)
        _fail_scene(production_id, scene.id, e)
        return None
    if isinstance(result, dict):
        _persist_video_result(production_id, scene, result)
    return result


def _complete_scene_video(
    production_id: str,
    scene: Any,
    video_uri: str,
    video_resolution: str | None = None,
) -> None:
    """Persist completed scene video URI + resolution and accumulate video cost."""
    res = (
        video_resolution
        or getattr(scene, "_video_resolution", None)
        or getattr(scene, "video_resolution", None)
        or "360p"
    )
    updates = {
        "status": "completed",
        "video_url": video_uri,
        "video_resolution": res,
        "error_message": None,
    }
    deps.firestore_svc.update_scene(production_id, scene.id, updates)
    scene.video_url = video_uri
    scene.video_resolution = res
    scene.status = "completed"
    model_id = getattr(scene, "_video_model_id", None) or DEFAULT_VIDEO_MODEL
    duration = _scene_duration_seconds(scene)
    accumulate_veo_cost_on("production", production_id, duration, model_id)
    rate = veo_rate_for(model_id)
    veo_cost = duration * rate.unit_cost_usd
    scene._video_usage = UsageMetrics(
        veo_videos=1,
        veo_seconds=duration,
        veo_model_id=model_id,
        veo_unit_cost=rate.unit_cost_usd,
        veo_cost_usd=veo_cost,
        cost_usd=veo_cost,
    )


async def _poll_scene_video(
    production_id: str, scene: Any, target_resolution: str | None = None
) -> bool:
    """Poll a scene's video operation until complete. Returns True on success."""
    op_name = getattr(scene, "_pending_op", None)
    if not op_name:
        return True
    poll_fn = get_hook("_poll_veo_operation", _poll_veo_operation)
    veo_status = await poll_fn(op_name)
    if veo_status.get("status") == "completed" and veo_status.get("video_uri"):
        _complete_scene_video(
            production_id, scene, veo_status["video_uri"], target_resolution
        )
        return True
    error = veo_status.get("error") or veo_status.get(
        "message", "Video generation failed"
    )
    scene._last_video_error = str(error)
    logger.error(
        f"Veo failed for scene {scene.id}: {error}",
        extra=log_extra(
            "_poll_scene_video", "veo_poll_failed", str(error), "fail_scene"
        ),
    )
    _fail_scene(production_id, scene.id, error)
    return False


def _scene_has_valid_video(scene: Any, quality: str, target_resolution: str) -> bool:
    """Determine if a scene's existing video can be reused without re-generating."""
    if not scene.video_url or not scene.video_url.startswith("gs://"):
        return False
    return scene.video_resolution == target_resolution or (
        quality == "draft" and bool(scene.video_url)
    )


async def _attempt_scene_video(
    production_id: str,
    scene: Any,
    production: Any,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Execute one attempt at generating and polling a scene video."""
    result = await _generate_scene_video(
        production_id,
        scene,
        production,
        quality=quality,
        target_resolution=target_resolution,
    )
    if result is None:
        return False
    if not isinstance(result, dict):
        if isinstance(result, str) and result.startswith("gs://"):
            _complete_scene_video(production_id, scene, result, target_resolution)
        return True
    op_name = result.get("operation_name")
    if op_name:
        scene._pending_op = op_name
        return await _poll_scene_video(production_id, scene, target_resolution)
    video_uri = result.get("video_uri")
    if video_uri and video_uri.startswith("gs://"):
        _complete_scene_video(production_id, scene, video_uri, target_resolution)
    return True


async def _retry_rai_text_to_video(
    production_id: str,
    scene: Any,
    production: Any,
    quality: str,
    target_resolution: str,
) -> bool:
    """Fallback to text-to-video when keyframe images trigger Responsible AI."""
    saved_start = scene.thumbnail_url
    saved_end = getattr(scene, "end_frame_url", None)
    if not (
        _is_rai_blocked_error(getattr(scene, "_last_video_error", None))
        and (saved_start or saved_end)
    ):
        return False
    logger.warning(
        f"Scene {scene.id} blocked with keyframe; retrying text-to-video fallback...",
        extra=log_extra(
            "_retry_rai_text_to_video",
            "rai_t2v_fallback",
            "keyframe_blocked",
            "clear_frames_and_retry",
        ),
    )
    scene.thumbnail_url = None
    scene.end_frame_url = None
    try:
        return await _attempt_scene_video(
            production_id,
            scene,
            production,
            quality=quality,
            target_resolution=target_resolution,
        )
    finally:
        scene.thumbnail_url = saved_start
        scene.end_frame_url = saved_end


async def _run_scene_video_stage(
    production_id: str,
    scene: Any,
    production: Any,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Kick off and poll video generation for a scene, with automatic RAI retry."""
    scene._last_video_error = None
    if await _attempt_scene_video(
        production_id, scene, production, quality, target_resolution
    ):
        return True
    last_err = getattr(scene, "_last_video_error", None)
    if not _is_rai_blocked_error(last_err):
        return False
    logger.warning(
        f"Scene {scene.id} hit Responsible AI filter ({last_err}); sanitizing and retrying...",
        extra=log_extra(
            "_run_scene_video_stage",
            "rai_video_retry",
            str(last_err),
            "sanitize_scene_prompt",
        ),
    )
    sanitized_desc = _sanitize_scene_for_rai(scene, production=production)
    scene_upd: dict[str, Any] = {
        "visual_description": sanitized_desc,
        "status": "generating",
        "error_message": None,
    }
    if getattr(scene, "narration", None) is not None:
        scene_upd["narration"] = scene.narration
    deps.firestore_svc.update_scene(production_id, scene.id, scene_upd)
    scene._last_video_error = None
    if await _attempt_scene_video(
        production_id, scene, production, quality, target_resolution
    ):
        return True
    return await _retry_rai_text_to_video(
        production_id, scene, production, quality, target_resolution
    )


async def _run_video_phase_for_scene(
    production_id: str,
    scene: Any,
    production: Any,
    video_sem: asyncio.Semaphore | None = None,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Phase 2B per-scene worker: generate video from start & end frames."""
    if _scene_has_valid_video(scene, quality, target_resolution):
        if scene.status != "completed":
            deps.firestore_svc.update_scene(
                production_id, scene.id, {"status": "completed", "error_message": None}
            )
        return True
    if video_sem is not None:
        async with video_sem:
            return await _run_scene_video_stage(
                production_id,
                scene,
                production,
                quality=quality,
                target_resolution=target_resolution,
            )
    return await _run_scene_video_stage(
        production_id,
        scene,
        production,
        quality=quality,
        target_resolution=target_resolution,
    )


async def _process_one_scene(
    production_id: str,
    scene: Any,
    production: Any,
    image_sem: asyncio.Semaphore | None = None,
    video_sem: asyncio.Semaphore | None = None,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Run frame -> video -> poll for a single scene using bounded semaphores."""
    frame_ok = await _run_frame_phase_for_scene(
        production_id,
        scene,
        production,
        image_sem=image_sem,
        quality=quality,
        target_resolution=target_resolution,
    )
    if not frame_ok:
        return False
    return await _run_video_phase_for_scene(
        production_id,
        scene,
        production,
        video_sem=video_sem,
        quality=quality,
        target_resolution=target_resolution,
    )


def _aggregate_video_usage(scenes: Any) -> tuple[UsageMetrics, int]:
    """Sum UsageMetrics across scenes that generated new video clips."""
    vid_count, vid_seconds, cost, unit_cost, model_id = 0, 0, 0.0, 0.0, ""
    for s in scenes:
        u = getattr(s, "_video_usage", None)
        if u is not None:
            vid_count += max(1, u.veo_videos)
            vid_seconds += u.veo_seconds
            cost += u.cost_usd
            unit_cost = u.veo_unit_cost or unit_cost
            model_id = u.veo_model_id or model_id
    metrics = UsageMetrics(
        veo_videos=vid_count,
        veo_seconds=vid_seconds,
        veo_model_id=model_id,
        veo_unit_cost=unit_cost,
        veo_cost_usd=cost,
        cost_usd=cost,
    )
    return metrics, vid_count

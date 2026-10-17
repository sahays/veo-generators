"""Stage 2A: Start and end keyframe generation and usage aggregation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import deps
from cost_tracking import accumulate_image_cost_on
from models import UsageMetrics
from render_pipeline.state import (
    _fail_scene,
    _is_rai_blocked_error,
    _sanitize_scene_for_rai,
    log_extra,
)

logger = logging.getLogger(__name__)


def _merge_frame_usage(
    existing: UsageMetrics | None, added: UsageMetrics
) -> UsageMetrics:
    """Combine UsageMetrics from start and end keyframe generations on a scene."""
    if existing is None:
        return UsageMetrics(
            image_generations=max(1, added.image_generations),
            image_input_tokens=added.image_input_tokens,
            image_output_tokens=added.image_output_tokens,
            image_model_name=added.image_model_name,
            image_cost_usd=added.image_cost_usd,
            cost_usd=added.cost_usd,
        )
    return UsageMetrics(
        image_generations=max(1, existing.image_generations)
        + max(1, added.image_generations),
        image_input_tokens=existing.image_input_tokens + added.image_input_tokens,
        image_output_tokens=existing.image_output_tokens + added.image_output_tokens,
        image_model_name=added.image_model_name or existing.image_model_name,
        image_cost_usd=existing.image_cost_usd + added.image_cost_usd,
        cost_usd=existing.cost_usd + added.cost_usd,
    )


def _record_frame_result(
    production_id: str, scene: Any, frame_result: Any, frame_position: str = "start"
) -> None:
    """Persist start or end frame URI + accumulate image cost; mutate scene object."""
    gcs_uri = frame_result.data["image_url"]
    prompt = frame_result.data.get("generated_prompt")
    if frame_position == "end":
        scene_updates = {"end_frame_url": gcs_uri}
        if prompt:
            scene_updates["end_frame_prompt"] = prompt
        scene.end_frame_url = gcs_uri
    else:
        scene_updates = {"thumbnail_url": gcs_uri}
        if prompt:
            scene_updates["generated_prompt"] = prompt
            scene_updates["image_prompt"] = prompt
        scene.thumbnail_url = gcs_uri
    deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)
    u = frame_result.usage
    accumulate_image_cost_on(
        "production",
        production_id,
        u.cost_usd,
        input_tokens=u.image_input_tokens,
        output_tokens=u.image_output_tokens,
        model_name=u.image_model_name,
    )
    scene._frame_usage = _merge_frame_usage(getattr(scene, "_frame_usage", None), u)


async def _call_generate_frame(
    production_id: str,
    scene: Any,
    production: Any,
    frame_position: str = "start",
    start_frame_uri: str | None = None,
) -> Any:
    """Call ai_svc.generate_frame with frame_position, falling back for legacy mocks."""
    if frame_position == "start":
        try:
            return await deps.ai_svc.generate_frame(
                production_id,
                scene,
                production.orientation,
                project=production,
                frame_position="start",
            )
        except TypeError:
            return await deps.ai_svc.generate_frame(
                production_id, scene, production.orientation, project=production
            )
    return await deps.ai_svc.generate_frame(
        production_id,
        scene,
        production.orientation,
        project=production,
        frame_position="end",
        start_frame_uri=start_frame_uri,
    )


async def _generate_start_frame(
    production_id: str, scene: Any, production: Any
) -> bool:
    """Generate start keyframe for a scene, with automatic RAI sanitize & retry."""
    try:
        res = await _call_generate_frame(production_id, scene, production, "start")
        _record_frame_result(production_id, scene, res, frame_position="start")
        return True
    except Exception as e:
        if not _is_rai_blocked_error(e):
            logger.error(
                f"Frame generation failed for scene {scene.id}: {e}",
                extra=log_extra(
                    "_generate_start_frame", "start_frame_failed", str(e), "abort_scene"
                ),
            )
            _fail_scene(production_id, scene.id, e)
            return False
        logger.warning(
            f"Start frame hit RAI filter for scene {scene.id}, sanitizing: {e}",
            extra=log_extra(
                "_generate_start_frame", "rai_sanitize_retry", str(e), "sanitize_prompt"
            ),
        )
        sanitized = _sanitize_scene_for_rai(scene)
        deps.firestore_svc.update_scene(
            production_id, scene.id, {"visual_description": sanitized}
        )
        try:
            res = await _call_generate_frame(production_id, scene, production, "start")
            _record_frame_result(production_id, scene, res, frame_position="start")
            return True
        except Exception as retry_err:
            logger.error(
                f"Start frame retry failed for scene {scene.id}: {retry_err}",
                extra=log_extra(
                    "_generate_start_frame",
                    "rai_retry_failed",
                    str(retry_err),
                    "abort_scene",
                ),
            )
            _fail_scene(production_id, scene.id, retry_err)
            return False


async def _generate_end_frame(production_id: str, scene: Any, production: Any) -> None:
    """Attempt end keyframe generation conditioned on the start frame URI."""
    try:
        end_res = await _call_generate_frame(
            production_id,
            scene,
            production,
            frame_position="end",
            start_frame_uri=scene.thumbnail_url,
        )
        if (
            end_res is not None
            and getattr(end_res, "data", None)
            and end_res.data.get("image_url")
        ):
            _record_frame_result(production_id, scene, end_res, frame_position="end")
    except (TypeError, StopIteration, RuntimeError) as compat_exc:
        logger.debug(
            f"End frame generation skipped for scene {scene.id}: {compat_exc}",
            extra=log_extra(
                "_generate_end_frame",
                "end_frame_skipped",
                str(compat_exc),
                "legacy_mock_fallback",
            ),
        )
    except Exception as e:
        logger.warning(
            f"End frame generation failed for scene {scene.id}, continuing: {e}",
            extra=log_extra(
                "_generate_end_frame",
                "end_frame_failed",
                str(e),
                "continue_with_start_frame",
            ),
        )


async def _generate_scene_frame(
    production_id: str, scene: Any, production: Any
) -> bool:
    """Generate both START frame (thumbnail_url) and END frame (end_frame_url) for a scene."""
    has_start = bool(scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"))
    end_url = getattr(scene, "end_frame_url", None)
    has_end = bool(end_url and end_url.startswith("gs://"))
    if has_start and has_end:
        scene._frame_usage = None
        return True
    deps.firestore_svc.update_scene(
        production_id, scene.id, {"status": "generating_frame", "error_message": None}
    )
    if not has_start and not await _generate_start_frame(
        production_id, scene, production
    ):
        return False
    if not has_end and scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
        await _generate_end_frame(production_id, scene, production)
    has_vid = bool(scene.video_url and scene.video_url.startswith("gs://"))
    restored_status = "completed" if has_vid else "pending"
    deps.firestore_svc.update_scene(
        production_id, scene.id, {"status": restored_status, "error_message": None}
    )
    scene.status = restored_status
    return True


async def _run_frame_phase_for_scene(
    production_id: str,
    scene: Any,
    production: Any,
    image_sem: asyncio.Semaphore | None = None,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Phase 2A per-scene worker: generate start & end frames for each scene."""
    _ = (quality, target_resolution)
    scene._frame_usage = None
    scene._video_usage = None
    if image_sem is not None:
        async with image_sem:
            return await _generate_scene_frame(production_id, scene, production)
    return await _generate_scene_frame(production_id, scene, production)


def _aggregate_frame_usage(scenes: Any) -> tuple[UsageMetrics, int]:
    """Sum UsageMetrics across scenes that generated new keyframes."""
    gen_count, in_tok, out_tok, cost, model_name = 0, 0, 0, 0.0, ""
    for s in scenes:
        u = getattr(s, "_frame_usage", None)
        if u is not None:
            gen_count += max(1, u.image_generations)
            in_tok += u.image_input_tokens
            out_tok += u.image_output_tokens
            cost += u.cost_usd
            model_name = u.image_model_name or model_name
    metrics = UsageMetrics(
        image_generations=gen_count,
        image_input_tokens=in_tok,
        image_output_tokens=out_tok,
        image_model_name=model_name,
        image_cost_usd=cost,
        cost_usd=cost,
    )
    return metrics, gen_count

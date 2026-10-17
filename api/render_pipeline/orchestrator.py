"""Main 5-stage render pipeline orchestrator (`process_render`)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import deps
from models import ProjectStatus
from render_pipeline.eval_regen import (
    run_selective_regenerate_step,
    run_storyboard_review_step,
    run_video_eval_step,
)
from render_pipeline.frames import _aggregate_frame_usage, _run_frame_phase_for_scene
from render_pipeline.state import (
    _ensure_steps_list,
    _fail_production,
    _fail_scene,
    _image_concurrency,
    _update_pipeline_step,
    _video_concurrency,
    get_hook,
    log_extra,
)
from render_pipeline.stitch import _stitch_production
from render_pipeline.videos import _aggregate_video_usage, _run_video_phase_for_scene

logger = logging.getLogger(__name__)


def _resolve_render_targets(
    production: Any, quality: str | None, resolution: str | None
) -> tuple[str, str]:
    """Determine `(effective_quality, target_resolution)` for a render run."""
    effective_quality = (
        quality or getattr(production, "render_quality", None) or "draft"
    )
    if effective_quality == "draft":
        target_resolution = resolution or "360p"
    else:
        raw_res = resolution or getattr(production, "video_resolution", None) or "720p"
        target_resolution = "720p" if raw_res == "360p" else raw_res
    return effective_quality, target_resolution


def _check_batch_failures(
    production_id: str, scenes: list[Any], results: list[Any], phase_label: str
) -> list[str]:
    """Log unhandled scene exceptions and return list of failed scene IDs."""
    failed: list[str] = []
    for scene, outcome in zip(scenes, results):
        if isinstance(outcome, Exception):
            logger.error(
                f"Scene {scene.id} {phase_label} raised unhandled error: {outcome}",
                extra=log_extra(
                    "_check_batch_failures",
                    f"{phase_label}_unhandled_error",
                    str(outcome),
                    "fail_scene",
                ),
            )
            _fail_scene(production_id, scene.id, outcome)
            failed.append(scene.id)
        elif not outcome:
            failed.append(scene.id)
    return failed


async def _execute_frames_stage(
    production_id: str,
    production: Any,
    steps: list[dict[str, Any]],
    image_sem: asyncio.Semaphore,
    effective_quality: str,
    target_resolution: str,
) -> bool:
    """Run Stage 2A (Start & End Keyframe Generation) across all scenes."""
    start_msg = (
        f"Generating start & end keyframes across {len(production.scenes)} scene(s)..."
    )
    _update_pipeline_step(
        production_id,
        steps,
        "generate_frames",
        "running",
        start_msg,
        extra_updates={"status": ProjectStatus.GENERATING},
    )
    tasks = [
        _run_frame_phase_for_scene(
            production_id,
            s,
            production,
            image_sem=image_sem,
            quality=effective_quality,
            target_resolution=target_resolution,
        )
        for s in production.scenes
    ]
    frame_results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = _check_batch_failures(
        production_id, production.scenes, frame_results, "frame"
    )
    if failed:
        msg = f"Keyframe generation failed for scene(s): {', '.join(failed)}"
        _update_pipeline_step(production_id, steps, "generate_frames", "failed", msg)
        _fail_production(production_id, msg, steps=steps)
        return False
    frame_usage, gen_frames = _aggregate_frame_usage(production.scenes)
    new_cnt = sum(
        1 for s in production.scenes if getattr(s, "_frame_usage", None) is not None
    )
    reused = len(production.scenes) - new_cnt
    reuse_txt = f", reused {reused} scene(s)" if reused else ""
    tok_txt = f"{frame_usage.image_input_tokens:,} in / {frame_usage.image_output_tokens:,} out tokens"
    detail = f"Generated {gen_frames} start/end frame(s){reuse_txt} • {tok_txt} (${frame_usage.cost_usd:.4f})"
    _update_pipeline_step(
        production_id,
        steps,
        "generate_frames",
        "completed",
        detail=detail,
        usage=frame_usage,
    )
    return True


async def _execute_videos_stage(
    production_id: str,
    production: Any,
    steps: list[dict[str, Any]],
    video_sem: asyncio.Semaphore,
    effective_quality: str,
    target_resolution: str,
) -> bool:
    """Run Stage 2B (Scene Video Generation) across all scenes."""
    start_msg = f"Generating {target_resolution} ({effective_quality}) videos from start & end frames..."
    _update_pipeline_step(
        production_id,
        steps,
        "generate_videos",
        "running",
        start_msg,
        extra_updates={"status": ProjectStatus.GENERATING},
    )
    tasks = [
        _run_video_phase_for_scene(
            production_id,
            s,
            production,
            video_sem=video_sem,
            quality=effective_quality,
            target_resolution=target_resolution,
        )
        for s in production.scenes
    ]
    video_results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = _check_batch_failures(
        production_id, production.scenes, video_results, "video"
    )
    if failed:
        msg = f"Generation failed for scene(s): {', '.join(failed)}"
        _update_pipeline_step(production_id, steps, "generate_videos", "failed", msg)
        _fail_production(production_id, msg, steps=steps)
        return False
    video_usage, gen_videos = _aggregate_video_usage(production.scenes)
    reused = len(production.scenes) - gen_videos
    reuse_txt = f", reused {reused}" if reused else ""
    detail = f"Generated {gen_videos} clip(s) at {target_resolution}{reuse_txt} • {video_usage.veo_seconds}s (${video_usage.cost_usd:.4f})"
    _update_pipeline_step(
        production_id,
        steps,
        "generate_videos",
        "completed",
        detail=detail,
        usage=video_usage,
    )
    return True


async def _execute_eval_and_regen_stages(
    production_id: str,
    production: Any,
    steps: list[dict[str, Any]],
    stitched_uri: str,
    effective_quality: str,
    target_resolution: str,
    auto_eval: bool,
    max_eval_iterations: int,
) -> bool:
    """Run Stage 4 (Multimodal Video Eval) and Stage 5 (Selective Auto-Regeneration)."""
    eval_report = None
    if auto_eval and hasattr(deps.ai_svc, "evaluate_finished_video"):
        eval_report = await run_video_eval_step(
            production_id,
            production=production,
            stitched_uri=stitched_uri,
            iteration=1,
            steps=steps,
        )
        production = deps.firestore_svc.get_production(production_id) or production
    else:
        _update_pipeline_step(
            production_id,
            steps,
            "evaluate_video",
            "skipped",
            "Skipped finished-video evaluation",
        )
    needs_regen = (
        auto_eval
        and eval_report is not None
        and not eval_report.passed
        and bool(eval_report.findings)
        and max_eval_iterations > 0
    )
    if needs_regen:
        return await run_selective_regenerate_step(
            production_id,
            production=production,
            eval_report=eval_report,
            quality=effective_quality,
            target_resolution=target_resolution,
            steps=steps,
        )
    skip_msg = (
        "All scenes passed evaluation"
        if (eval_report and eval_report.passed)
        else "Skipped selective regeneration"
    )
    _update_pipeline_step(
        production_id, steps, "regenerate_scenes", "skipped", skip_msg
    )
    return True


async def _run_render_stages(
    production_id: str,
    production: Any,
    steps: list[dict[str, Any]],
    effective_quality: str,
    target_resolution: str,
    auto_review: bool,
    auto_eval: bool,
    max_eval_iterations: int,
) -> None:
    """Execute Stages 1 through 5 sequentially for `process_render`."""
    image_sem, video_sem = (
        asyncio.Semaphore(_image_concurrency()),
        asyncio.Semaphore(_video_concurrency()),
    )
    if auto_review and hasattr(deps.ai_svc, "review_storyboard"):
        await run_storyboard_review_step(
            production_id, production=production, steps=steps
        )
        production = deps.firestore_svc.get_production(production_id) or production
    else:
        _update_pipeline_step(
            production_id,
            steps,
            "review_storyboard",
            "skipped",
            "Skipped storyboard review",
        )
    if not await _execute_frames_stage(
        production_id,
        production,
        steps,
        image_sem,
        effective_quality,
        target_resolution,
    ):
        return
    if not await _execute_videos_stage(
        production_id,
        production,
        steps,
        video_sem,
        effective_quality,
        target_resolution,
    ):
        return
    production = deps.firestore_svc.get_production(production_id) or production
    stitch_fn = get_hook("_stitch_production", _stitch_production)
    stitched_uri = await stitch_fn(
        production_id,
        production,
        quality=effective_quality,
        resolution=target_resolution,
        steps=steps,
    )
    if not stitched_uri:
        return
    production = deps.firestore_svc.get_production(production_id) or production
    if not await _execute_eval_and_regen_stages(
        production_id,
        production,
        steps,
        stitched_uri,
        effective_quality,
        target_resolution,
        auto_eval,
        max_eval_iterations,
    ):
        return
    done_payload = {
        "status": ProjectStatus.COMPLETED,
        "pipeline_stage": "completed",
        "pipeline_steps": steps,
        "error_message": None,
    }
    deps.firestore_svc.update_production(production_id, done_payload)


async def process_render(
    production_id: str,
    quality: str | None = None,
    resolution: str | None = None,
    auto_review: bool = True,
    auto_eval: bool = True,
    max_eval_iterations: int = 1,
) -> None:
    """5-stage agent-supervised render pipeline with per-step UsageMetrics."""
    if not deps.firestore_svc or not deps.ai_svc or not deps.video_svc:
        return
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    effective_quality, target_resolution = _resolve_render_targets(
        production, quality, resolution
    )
    steps = _ensure_steps_list(production, auto_review=auto_review, auto_eval=auto_eval)
    production.render_quality = effective_quality
    production.video_resolution = target_resolution
    deps.firestore_svc.update_production(
        production_id,
        {
            "render_quality": effective_quality,
            "video_resolution": target_resolution,
            "pipeline_steps": steps,
        },
    )
    try:
        await _run_render_stages(
            production_id,
            production,
            steps,
            effective_quality,
            target_resolution,
            auto_review,
            auto_eval,
            max_eval_iterations,
        )
    except Exception as e:
        logger.error(
            f"Render failed for {production_id}: {e}",
            extra=log_extra(
                "process_render", "render_pipeline_failed", str(e), "fail_production"
            ),
        )
        _fail_production(production_id, str(e), steps=steps)

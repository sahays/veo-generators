"""Stages 1, 4, and 5: Storyboard review, multimodal video evaluation, and selective regeneration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import deps
from models import ProjectStatus, UsageMetrics
from pricing_config import TRANSCODER_HD, TRANSCODER_SD
from render_pipeline.frames import _aggregate_frame_usage, _run_frame_phase_for_scene
from render_pipeline.review_eval import (  # noqa: F401
    _apply_eval_findings_to_scenes,
    run_storyboard_review_step,
    run_video_eval_step,
)
from render_pipeline.state import (
    _ensure_steps_list,
    _fail_production,
    _fail_scene,
    _image_concurrency,
    _scene_duration_seconds,
    _update_pipeline_step,
    _video_concurrency,
    get_hook,
    log_extra,
)
from render_pipeline.stitch import _stitch_production
from render_pipeline.videos import _aggregate_video_usage, _run_video_phase_for_scene

logger = logging.getLogger(__name__)


def _apply_finding_to_scene(scene: Any, finding: Any) -> None:
    """Apply corrective prompt fields from a single evaluation finding to `scene`."""
    if finding.corrected_visual_description:
        scene.visual_description = finding.corrected_visual_description
    if finding.corrected_speaker_notes:
        scene.speaker_notes = finding.corrected_speaker_notes
    if finding.corrected_narration:
        scene.narration = finding.corrected_narration
        scene.narration_enabled = True
    if finding.corrected_music_description:
        scene.music_description = finding.corrected_music_description
        scene.music_enabled = True
    scene.eval_feedback = finding.observed_issue
    scene.video_url = None
    if finding.regenerate_frame:
        scene.thumbnail_url = None
        scene.end_frame_url = None
    scene.regen_count = (scene.regen_count or 0) + 1
    scene.eval_status = "regenerating"
    scene._frame_usage = None
    scene._video_usage = None


def _prepare_flagged_scenes(production: Any, eval_report: Any) -> list[Any]:
    """Mutate and return scenes matched by `eval_report.findings`."""
    flagged_scenes: list[Any] = []
    for idx, scene in enumerate(production.scenes):
        finding = next(
            (
                f
                for f in eval_report.findings
                if f.scene_id == scene.id or f.scene_number == idx + 1
            ),
            None,
        )
        if finding is not None:
            _apply_finding_to_scene(scene, finding)
            flagged_scenes.append(scene)
    return flagged_scenes


def _collect_phase_failures(
    production_id: str, scenes: list[Any], outcomes: list[Any], label: str
) -> list[str]:
    """Inspect asyncio.gather outcomes and record failed scene IDs."""
    failed_ids: list[str] = []
    for s, outcome in zip(scenes, outcomes):
        if isinstance(outcome, Exception):
            logger.error(
                f"Regeneration {label} failed for scene {s.id}: {outcome}",
                extra=log_extra(
                    "_collect_phase_failures",
                    f"regen_{label}_error",
                    str(outcome),
                    "fail_scene",
                ),
            )
            _fail_scene(production_id, s.id, outcome)
            failed_ids.append(s.id)
        elif not outcome:
            failed_ids.append(s.id)
    return failed_ids


async def _execute_flagged_regeneration(
    production_id: str,
    production: Any,
    flagged_scenes: list[Any],
    quality: str,
    target_resolution: str,
) -> list[str]:
    """Run Phase 5A (frames) and Phase 5B (videos) for flagged scenes; return failed IDs."""
    image_sem = asyncio.Semaphore(_image_concurrency())
    video_sem = asyncio.Semaphore(_video_concurrency())
    frame_results = await asyncio.gather(
        *(
            _run_frame_phase_for_scene(
                production_id,
                s,
                production,
                image_sem=image_sem,
                quality=quality,
                target_resolution=target_resolution,
            )
            for s in flagged_scenes
        ),
        return_exceptions=True,
    )
    failed_ids = _collect_phase_failures(
        production_id, flagged_scenes, frame_results, "frame"
    )
    if failed_ids:
        return failed_ids
    video_results = await asyncio.gather(
        *(
            _run_video_phase_for_scene(
                production_id,
                s,
                production,
                video_sem=video_sem,
                quality=quality,
                target_resolution=target_resolution,
            )
            for s in flagged_scenes
        ),
        return_exceptions=True,
    )
    return _collect_phase_failures(
        production_id, flagged_scenes, video_results, "video"
    )


def _build_combined_regen_usage(
    refreshed_prod: Any,
    frame_usage: UsageMetrics,
    video_usage: UsageMetrics,
    target_resolution: str,
) -> tuple[UsageMetrics, float]:
    """Combine frame, video, and transcoder costs for the selective regeneration step."""
    tier = TRANSCODER_SD if target_resolution == "360p" else TRANSCODER_HD
    total_seconds = sum(_scene_duration_seconds(s) for s in refreshed_prod.scenes)
    minutes = total_seconds / 60.0
    transcoder_cost = minutes * tier.unit_cost_usd
    total_regen_cost = frame_usage.cost_usd + video_usage.cost_usd + transcoder_cost
    combined = UsageMetrics(
        image_generations=frame_usage.image_generations,
        image_input_tokens=frame_usage.image_input_tokens,
        image_output_tokens=frame_usage.image_output_tokens,
        image_model_name=frame_usage.image_model_name,
        image_cost_usd=frame_usage.image_cost_usd,
        veo_videos=video_usage.veo_videos,
        veo_seconds=video_usage.veo_seconds,
        veo_model_id=video_usage.veo_model_id,
        veo_unit_cost=video_usage.veo_unit_cost,
        veo_cost_usd=video_usage.veo_cost_usd,
        transcoder_minutes=minutes,
        transcoder_tier=tier.id.replace("transcoder_", ""),
        transcoder_cost_usd=transcoder_cost,
        cost_usd=total_regen_cost,
    )
    return combined, total_regen_cost


def _finalize_regenerated_scenes(
    production_id: str,
    refreshed_prod: Any,
    flagged_scenes: list[Any],
    eval_report: Any,
    steps: list[dict[str, Any]],
    frame_usage: UsageMetrics,
    regen_frames: int,
    video_usage: UsageMetrics,
    regen_videos: int,
    target_resolution: str,
) -> None:
    """Persist regenerated scene statuses and combined usage metrics to Firestore."""
    combined_usage, total_regen_cost = _build_combined_regen_usage(
        refreshed_prod, frame_usage, video_usage, target_resolution
    )
    refreshed_prod = deps.firestore_svc.get_production(production_id) or refreshed_prod
    regen_ids = {s.id for s in flagged_scenes}
    for s in refreshed_prod.scenes:
        if s.id in regen_ids:
            s.eval_status = "regenerated"
    eval_report.regenerated_scene_ids = [s.id for s in flagged_scenes]
    detail = (
        f"Regenerated {regen_videos} video(s), {regen_frames} frame(s) & re-stitched • "
        f"${total_regen_cost:.4f}"
    )
    extra = {
        "scenes": [s.dict() for s in refreshed_prod.scenes],
        "eval_report": eval_report.dict(),
    }
    _update_pipeline_step(
        production_id,
        steps,
        "regenerate_scenes",
        "completed",
        detail=detail,
        usage=combined_usage,
        extra_updates=extra,
    )


async def _restitch_and_finalize_regen(
    production_id: str,
    production: Any,
    flagged_scenes: list[Any],
    eval_report: Any,
    steps: list[dict[str, Any]],
    quality: str,
    target_resolution: str,
) -> bool:
    """Re-stitch regenerated scenes and finalize usage metrics."""
    frame_usage, regen_frames = _aggregate_frame_usage(flagged_scenes)
    video_usage, regen_videos = _aggregate_video_usage(flagged_scenes)
    refreshed_prod = deps.firestore_svc.get_production(production_id) or production
    stitch_fn = get_hook("_stitch_production", _stitch_production)
    restitched_uri = await stitch_fn(
        production_id,
        refreshed_prod,
        quality=quality,
        resolution=target_resolution,
        steps=None,
    )
    if not restitched_uri:
        _update_pipeline_step(
            production_id,
            steps,
            "regenerate_scenes",
            "failed",
            "Re-stitching failed after scene regeneration",
        )
        return False
    _finalize_regenerated_scenes(
        production_id,
        refreshed_prod,
        flagged_scenes,
        eval_report,
        steps,
        frame_usage,
        regen_frames,
        video_usage,
        regen_videos,
        target_resolution,
    )
    return True


async def run_selective_regenerate_step(
    production_id: str,
    production: Any = None,
    eval_report: Any = None,
    quality: str = "draft",
    target_resolution: str = "360p",
    steps: list[dict[str, Any]] | None = None,
) -> bool:
    """Stage 5: Apply corrective prompt updates to flagged scenes, re-render, and re-stitch."""
    production = production or deps.firestore_svc.get_production(production_id)
    if not production:
        return False
    eval_report = eval_report or production.eval_report
    if not eval_report or not eval_report.findings:
        return True
    steps = (
        steps if steps is not None else _ensure_steps_list(production, auto_eval=True)
    )
    flagged_scenes = _prepare_flagged_scenes(production, eval_report)
    if not flagged_scenes:
        _update_pipeline_step(
            production_id,
            steps,
            "regenerate_scenes",
            "skipped",
            "No scenes required regeneration",
        )
        return True
    run_msg = (
        f"Regenerating keyframes & videos for {len(flagged_scenes)} flagged scene(s)..."
    )
    extra = {
        "status": ProjectStatus.REGENERATING,
        "scenes": [s.dict() for s in production.scenes],
    }
    _update_pipeline_step(
        production_id,
        steps,
        "regenerate_scenes",
        "running",
        run_msg,
        extra_updates=extra,
    )
    failed_ids = await _execute_flagged_regeneration(
        production_id, production, flagged_scenes, quality, target_resolution
    )
    if failed_ids:
        joined = ", ".join(failed_ids)
        _update_pipeline_step(
            production_id,
            steps,
            "regenerate_scenes",
            "failed",
            f"Regeneration failed for scene(s): {joined}",
        )
        _fail_production(
            production_id, f"Selective regeneration failed for scene(s): {joined}"
        )
        return False
    return await _restitch_and_finalize_regen(
        production_id,
        production,
        flagged_scenes,
        eval_report,
        steps,
        quality,
        target_resolution,
    )


async def run_standalone_regenerate_flagged(production_id: str) -> None:
    """Background task entry point for POST /productions/{id}/regenerate-flagged."""
    if not deps.firestore_svc:
        return
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return
    quality = getattr(production, "render_quality", None) or "draft"
    resolution = getattr(production, "video_resolution", None) or (
        "360p" if quality == "draft" else "720p"
    )
    steps = _ensure_steps_list(production, auto_eval=True)
    ok = await run_selective_regenerate_step(
        production_id,
        production=production,
        eval_report=production.eval_report,
        quality=quality,
        target_resolution=resolution,
        steps=steps,
    )
    if ok:
        deps.firestore_svc.update_production(
            production_id,
            {
                "status": ProjectStatus.COMPLETED,
                "pipeline_stage": "completed",
                "pipeline_steps": steps,
                "error_message": None,
            },
        )

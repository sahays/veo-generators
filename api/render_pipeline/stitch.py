"""Stage 3: Video transcoding and FFmpeg fallback stitching."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
import tempfile
from typing import Any

import deps
from cost_tracking import accumulate_transcoder_cost
from models import ProjectStatus, UsageMetrics
from pricing_config import TRANSCODER_HD, TRANSCODER_SD
from promo_service import concatenate_with_crossfade, normalize_segment
from render_pipeline.state import (
    _fail_production,
    _scene_duration_seconds,
    _update_pipeline_step,
    get_hook,
    log_extra,
)

logger = logging.getLogger(__name__)


def _collect_scene_uris(production_id: str, production: Any) -> list[str] | None:
    """Validate every scene has a GCS video and return ordered URIs."""
    uris: list[str] = []
    for scene in production.scenes:
        if not scene.video_url or not scene.video_url.startswith("gs://"):
            logger.error(
                f"Scene {scene.id} missing video after render loop",
                extra=log_extra(
                    "_collect_scene_uris",
                    "missing_scene_video",
                    scene.id,
                    "fail_production",
                ),
            )
            _fail_production(production_id, f"Scene {scene.id} missing video")
            return None
        uris.append(scene.video_url)
    return uris


def _compute_stitch_usage(
    production_id: str, production: Any, resolution: str = "720p"
) -> UsageMetrics:
    """Accumulate transcoder cost and return step-level UsageMetrics."""
    tier = TRANSCODER_SD if resolution == "360p" else TRANSCODER_HD
    total_seconds = sum(_scene_duration_seconds(s) for s in production.scenes)
    minutes = total_seconds / 60.0
    accumulate_transcoder_cost("production", production_id, minutes, tier=tier)
    tier_id = tier.id.replace("transcoder_", "")
    cost = minutes * tier.unit_cost_usd
    return UsageMetrics(
        transcoder_minutes=minutes,
        transcoder_tier=tier_id,
        transcoder_cost_usd=cost,
        cost_usd=cost,
    )


async def _wait_for_stitch(
    production_id: str,
    production: Any,
    job_name: str,
    interval: int = 10,
    resolution: str = "720p",
) -> bool:
    """Poll the transcoder job until it terminates; return True on SUCCEEDED."""
    while True:
        await asyncio.sleep(interval)
        state = await asyncio.to_thread(deps.transcoder_svc.get_job_status, job_name)
        if state == "SUCCEEDED":
            deps.firestore_svc.update_production(
                production_id, {"status": ProjectStatus.COMPLETED}
            )
            _compute_stitch_usage(production_id, production, resolution=resolution)
            logger.info(
                f"Production {production_id} completed successfully",
                extra=log_extra(
                    "_wait_for_stitch",
                    "transcoder_succeeded",
                    job_name,
                    "mark_completed",
                ),
            )
            return True
        if state in ("FAILED", "UNKNOWN"):
            logger.warning(
                f"Transcoder job {job_name} ended with state {state}",
                extra=log_extra(
                    "_wait_for_stitch", "transcoder_failed", state, "fallback_to_ffmpeg"
                ),
            )
            return False


def _resolve_stitch_dimensions(
    production_id: str, orientation: str, resolution: str
) -> tuple[str, int, int, str]:
    """Return `(mux_name, width, height, output_uri)` for FFmpeg stitching."""
    bucket = os.getenv("GCS_BUCKET", "aug18-25-3-veo-generators-media")
    if resolution == "360p":
        mux_name, base_w, base_h = "draft.mp4", 640, 360
    elif resolution == "1080p":
        mux_name, base_w, base_h = "final.mp4", 1920, 1080
    else:
        mux_name, base_w, base_h = "final.mp4", 1280, 720
    output_uri = f"gs://{bucket}/productions/{production_id}/stitched/{mux_name}"
    width, height = (base_h, base_w) if orientation == "9:16" else (base_w, base_h)
    return mux_name, width, height, output_uri


def _download_and_normalize_clips(
    scene_uris: list[str], width: int, height: int, temp_files: list[str]
) -> list[str]:
    """Download GCS clips to temp files and normalize resolution in parallel."""
    raw_paths: list[str] = []
    norm_paths: list[str] = []
    for idx, uri in enumerate(scene_uris):
        raw_fd, raw_path = tempfile.mkstemp(suffix=f"_raw_{idx}.mp4")
        os.close(raw_fd)
        temp_files.append(raw_path)
        deps.storage_svc.download_to_file(uri, raw_path)
        raw_paths.append(raw_path)
        norm_fd, norm_path = tempfile.mkstemp(suffix=f"_norm_{idx}.mp4")
        os.close(norm_fd)
        temp_files.append(norm_path)
        norm_paths.append(norm_path)
    with ThreadPoolExecutor(max_workers=min(4, len(raw_paths) or 1)) as pool:
        futures = [
            pool.submit(normalize_segment, r_p, n_p, width, height)
            for r_p, n_p in zip(raw_paths, norm_paths)
        ]
        for fut in futures:
            fut.result()
    return norm_paths


def _ffmpeg_stitch_scenes(
    production_id: str,
    scene_uris: list[str],
    orientation: str = "16:9",
    resolution: str = "720p",
) -> str:
    """Download scene clips, normalize in parallel, concatenate, and upload to GCS."""
    mux_name, width, height, output_uri = _resolve_stitch_dimensions(
        production_id, orientation, resolution
    )
    temp_files: list[str] = []
    try:
        norm_paths = _download_and_normalize_clips(
            scene_uris, width, height, temp_files
        )
        out_fd, out_path = tempfile.mkstemp(suffix=f"_{mux_name}")
        os.close(out_fd)
        temp_files.append(out_path)
        concatenate_with_crossfade(norm_paths, out_path, crossfade_duration=0.25)
        deps.storage_svc.upload_from_file(out_path, output_uri)
        return output_uri
    finally:
        for path in temp_files:
            try:
                os.unlink(path)
            except OSError:
                pass


def _preview_stitch_usage(
    production: Any, resolution: str
) -> tuple[UsageMetrics, float, float]:
    """Compute estimated transcoder usage metrics without mutating Firestore."""
    tier = TRANSCODER_SD if resolution == "360p" else TRANSCODER_HD
    total_seconds = sum(_scene_duration_seconds(s) for s in production.scenes)
    minutes = total_seconds / 60.0
    tier_id = tier.id.replace("transcoder_", "")
    stitch_cost = minutes * tier.unit_cost_usd
    usage = UsageMetrics(
        transcoder_minutes=minutes,
        transcoder_tier=tier_id,
        transcoder_cost_usd=stitch_cost,
        cost_usd=stitch_cost,
    )
    return usage, minutes, stitch_cost


async def _submit_transcoder_job(
    production_id: str, scene_uris: list[str], orientation: str | None, resolution: str
) -> tuple[str, str]:
    """Submit a Cloud Transcoder stitch job with legacy mock fallback."""
    try:
        return await asyncio.to_thread(
            deps.transcoder_svc.stitch_from_uris,
            production_id,
            scene_uris,
            orientation=orientation,
            resolution=resolution,
        )
    except TypeError:
        return await asyncio.to_thread(
            deps.transcoder_svc.stitch_from_uris,
            production_id,
            scene_uris,
            orientation=orientation,
        )


async def _try_transcoder_stitch(
    production_id: str,
    production: Any,
    scene_uris: list[str],
    resolution: str,
    is_draft: bool,
) -> tuple[bool, str | None]:
    """Attempt stitching via Cloud Transcoder and poll until completion."""
    if not deps.transcoder_svc:
        return False, None
    try:
        job_name, final_uri = await _submit_transcoder_job(
            production_id, scene_uris, production.orientation, resolution
        )
        url_updates: dict[str, Any] = {
            "stitch_job_name": job_name,
            "final_video_url": final_uri,
        }
        if is_draft:
            url_updates["draft_video_url"] = final_uri
        deps.firestore_svc.update_production(production_id, url_updates)
        wait_fn = get_hook("_wait_for_stitch", _wait_for_stitch)
        try:
            ok = await wait_fn(
                production_id, production, job_name, resolution=resolution
            )
        except TypeError:
            ok = await wait_fn(production_id, production, job_name)
        return ok, final_uri
    except Exception as e:
        logger.warning(
            f"Cloud Transcoder stitch failed for {production_id}, trying FFmpeg: {e}",
            extra=log_extra(
                "_try_transcoder_stitch",
                "transcoder_exception",
                str(e),
                "fallback_ffmpeg",
            ),
        )
        return False, None


async def _invoke_ffmpeg_stitch(
    production_id: str, scene_uris: list[str], orient: str, resolution: str
) -> str:
    """Invoke the FFmpeg stitch helper in a worker thread with legacy mock fallback."""
    ffmpeg_fn = get_hook("_ffmpeg_stitch_scenes", _ffmpeg_stitch_scenes)
    try:
        return await asyncio.to_thread(
            ffmpeg_fn, production_id, scene_uris, orient, resolution
        )
    except TypeError:
        return await asyncio.to_thread(ffmpeg_fn, production_id, scene_uris, orient)


async def _try_ffmpeg_stitch(
    production_id: str,
    production: Any,
    scene_uris: list[str],
    resolution: str,
    is_draft: bool,
    steps: list[dict[str, Any]] | None,
) -> str | None:
    """Execute FFmpeg fallback stitching and update production status."""
    orient = production.orientation or "16:9"
    try:
        logger.info(
            f"Running FFmpeg stitch fallback for production {production_id}",
            extra=log_extra(
                "_try_ffmpeg_stitch",
                "ffmpeg_fallback_start",
                production_id,
                "thread_pool",
            ),
        )
        final_uri = await _invoke_ffmpeg_stitch(
            production_id, scene_uris, orient, resolution
        )
        url_updates: dict[str, Any] = {
            "status": ProjectStatus.COMPLETED,
            "final_video_url": final_uri,
            "error_message": None,
        }
        if is_draft:
            url_updates["draft_video_url"] = final_uri
        deps.firestore_svc.update_production(production_id, url_updates)
        if steps is not None:
            msg = f"Stitched {len(scene_uris)} clips via FFmpeg ({resolution})"
            _update_pipeline_step(
                production_id,
                steps,
                "stitch_video",
                "completed",
                msg,
                usage=UsageMetrics(),
            )
        logger.info(
            f"Production {production_id} stitched via FFmpeg: {final_uri}",
            extra=log_extra(
                "_try_ffmpeg_stitch",
                "ffmpeg_fallback_done",
                str(final_uri),
                "completed",
            ),
        )
        return final_uri
    except Exception as e:
        logger.error(
            f"FFmpeg stitch fallback failed for {production_id}: {e}",
            extra=log_extra(
                "_try_ffmpeg_stitch",
                "ffmpeg_fallback_failed",
                str(e),
                "fail_production",
            ),
        )
        if steps is not None:
            _update_pipeline_step(
                production_id, steps, "stitch_video", "failed", str(e)
            )
        _fail_production(production_id, f"Stitching failed: {e}")
        return None


def _mark_stitch_running(
    production_id: str,
    clip_count: int,
    resolution: str,
    steps: list[dict[str, Any]] | None,
) -> None:
    """Record the start of Stage 3 (stitching) in Firestore."""
    extra = {"status": ProjectStatus.STITCHING, "error_message": None}
    if steps is not None:
        msg = f"Stitching {clip_count} scene clips at {resolution}..."
        _update_pipeline_step(
            production_id, steps, "stitch_video", "running", msg, extra_updates=extra
        )
    else:
        deps.firestore_svc.update_production(production_id, extra)


async def _stitch_production(
    production_id: str,
    production: Any,
    quality: str = "final",
    resolution: str = "720p",
    steps: list[dict[str, Any]] | None = None,
) -> str | None:
    """Combine all scene videos into a final/draft video via Transcoder (with FFmpeg fallback)."""
    scene_uris = _collect_scene_uris(production_id, production)
    if scene_uris is None:
        if steps is not None:
            _update_pipeline_step(
                production_id, steps, "stitch_video", "failed", "Missing scene video"
            )
        return None
    _mark_stitch_running(production_id, len(scene_uris), resolution, steps)
    is_draft = quality == "draft" or resolution == "360p"
    stitch_usage, minutes, stitch_cost = _preview_stitch_usage(production, resolution)
    transcoder_ok, final_uri = await _try_transcoder_stitch(
        production_id, production, scene_uris, resolution, is_draft
    )
    if transcoder_ok and final_uri:
        if steps is not None:
            msg = f"Stitched {len(scene_uris)} clips ({resolution}) • {minutes:.2f} min (${stitch_cost:.4f})"
            _update_pipeline_step(
                production_id,
                steps,
                "stitch_video",
                "completed",
                msg,
                usage=stitch_usage,
            )
        return final_uri
    if not deps.storage_svc:
        err = "Transcoder stitch failed and storage unavailable"
        if steps is not None:
            _update_pipeline_step(production_id, steps, "stitch_video", "failed", err)
        _fail_production(production_id, err)
        return None
    return await _try_ffmpeg_stitch(
        production_id, production, scene_uris, resolution, is_draft, steps
    )

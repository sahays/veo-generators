"""Render state machine — 5-stage agent-supervised pipeline:
1. Storyboard Continuity & Realism Review
2. Parallel Keyframe & Video Generation (360p Draft / 720p-1080p Final)
3. Video Transcoding & Stitching
4. Multimodal Finished-Video Evaluation
5. Selective Auto-Regeneration & Re-Stitch

All state and per-step UsageMetrics are persisted to Firestore so the frontend
can poll GET /productions/{id} at any point in the pipeline.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
import os
import tempfile

import deps
from cost_tracking import (
    accumulate_image_cost_on,
    accumulate_text_cost_on,
    accumulate_transcoder_cost,
    accumulate_veo_cost_on,
)
from helpers import parse_timestamp
from models import PipelineStepLog, ProjectStatus, UsageMetrics
from pricing_config import (
    DEFAULT_VIDEO_MODEL,
    TRANSCODER_HD,
    TRANSCODER_SD,
    veo_rate_for,
)
from promo_service import concatenate_with_crossfade, normalize_segment

logger = logging.getLogger(__name__)

DEFAULT_IMAGE_CONCURRENCY = 4
DEFAULT_VIDEO_CONCURRENCY = 4


def _image_concurrency() -> int:
    return max(
        1, int(os.getenv("RENDER_IMAGE_CONCURRENCY", str(DEFAULT_IMAGE_CONCURRENCY)))
    )


def _video_concurrency() -> int:
    return max(
        1, int(os.getenv("RENDER_VIDEO_CONCURRENCY", str(DEFAULT_VIDEO_CONCURRENCY)))
    )


def _scene_duration_seconds(scene) -> int:
    """Veo billing duration: clipped into [4, 8]; defaults to 8 on parse error."""
    try:
        start = parse_timestamp(scene.timestamp_start)
        end = parse_timestamp(scene.timestamp_end)
        return max(4, min(8, int(end - start)))
    except (ValueError, IndexError):
        return 8


def build_initial_pipeline_steps(
    auto_review: bool = True, auto_eval: bool = True
) -> list[dict]:
    """Create initial PipelineStepLog entries for the 5-stage render pipeline."""
    entries = [
        PipelineStepLog(
            step_id="review_storyboard",
            label="Storyboard Continuity & Realism Review",
            status="pending" if auto_review else "skipped",
        ),
        PipelineStepLog(
            step_id="generate_frames",
            label="Start & End Keyframe Generation",
            status="pending",
        ),
        PipelineStepLog(
            step_id="generate_videos",
            label="Scene Video Generation",
            status="pending",
        ),
        PipelineStepLog(
            step_id="stitch_video",
            label="Video Transcoding & Stitching",
            status="pending",
        ),
        PipelineStepLog(
            step_id="evaluate_video",
            label="Multimodal Finished-Video Evaluation",
            status="pending" if auto_eval else "skipped",
        ),
        PipelineStepLog(
            step_id="regenerate_scenes",
            label="Selective Auto-Regeneration & Re-Stitch",
            status="pending" if auto_eval else "skipped",
        ),
    ]
    return [e.dict() for e in entries]


def _ensure_steps_list(
    production, auto_review: bool = True, auto_eval: bool = True
) -> list[dict]:
    raw_steps = getattr(production, "pipeline_steps", None) or []
    if not raw_steps:
        return build_initial_pipeline_steps(
            auto_review=auto_review, auto_eval=auto_eval
        )
    return [s.dict() if hasattr(s, "dict") else dict(s) for s in raw_steps]


def _update_pipeline_step(
    production_id: str,
    steps: list[dict],
    step_id: str,
    status: str,
    detail: str = "",
    usage: UsageMetrics | None = None,
    extra_updates: dict | None = None,
) -> None:
    """Update a step in `steps` and persist pipeline progress to Firestore."""
    now = datetime.utcnow()
    for step in steps:
        if step.get("step_id") == step_id:
            step["status"] = status
            if status == "running" and not step.get("started_at"):
                step["started_at"] = now
            if status in ("completed", "skipped", "failed"):
                step["completed_at"] = now
            if detail:
                step["detail"] = detail
            if usage is not None:
                step["usage"] = usage.dict() if hasattr(usage, "dict") else usage
            break

    if deps.firestore_svc:
        payload = {
            "pipeline_stage": step_id,
            "pipeline_steps": steps,
            **(extra_updates or {}),
        }
        deps.firestore_svc.update_production(production_id, payload)


def _fail_production(
    production_id: str,
    error_message: str,
    steps: list[dict] | None = None,
) -> None:
    payload: dict = {
        "status": ProjectStatus.FAILED,
        "error_message": error_message,
    }
    if steps is not None:
        now = datetime.utcnow()
        for step in steps:
            if step.get("status") == "running":
                step["status"] = "failed"
                step["completed_at"] = now
                if not step.get("detail"):
                    step["detail"] = error_message
        payload["pipeline_steps"] = steps
        payload["pipeline_stage"] = "failed"
    deps.firestore_svc.update_production(production_id, payload)


def _fail_scene(production_id: str, scene_id: str, error: Exception | str) -> None:
    deps.firestore_svc.update_scene(
        production_id,
        scene_id,
        {"status": "failed", "error_message": str(error)},
    )


async def _poll_veo_operation(operation_name: str, timeout: int = 600) -> dict:
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


_RAI_REPLACEMENTS = (
    ("Chibi", "Stylized 3D animated"),
    ("chibi", "stylized 3D animated"),
    ("burning palace", "dramatically lit palace"),
    ("burning", "warmly illuminated"),
    ("burn", "illuminate"),
    ("blazes", "glows brightly"),
    ("blazing", "radiantly glowing"),
    ("blaze", "radiant glow"),
    ("ignites", "shimmers with light"),
    ("ignite", "shimmer with golden light"),
    ("ignited", "illuminated"),
    ("roaring orange flames", "dramatic golden-amber light"),
    ("roaring flames", "golden-amber radiance"),
    ("flames", "golden-orange light"),
    ("flame", "warm golden light"),
    ("on fire", "bathed in dramatic amber glow"),
    ("cotton-candy fire", "whimsical pastel light"),
    ("fire", "warm amber glow"),
    ("smoke clouds", "magical aurora mist"),
    ("smoke", "luminous mist"),
    ("embers", "golden sparkles"),
    ("sparks", "starlight sparkles"),
    ("destruction", "dramatic transformation"),
    ("destroyed", "transformed"),
    ("explosion", "burst of golden light"),
    ("battlefield", "epic mythic arena"),
    ("blood", "crimson dust"),
    ("kill", "defeat"),
    ("killing", "overcoming"),
    ("attack", "confront"),
    ("attacking", "confronting"),
    ("weapon", "ornate ceremonial staff"),
    ("weapons", "ornate ceremonial artifacts"),
)

_RAI_NARRATION_REPLACEMENTS = (
    ("अग्नि", "दिव्य ज्योति"),
    ("आग", "दिव्य आभा"),
    ("भस्म कर दिया", "प्रकाशमान कर दिया"),
    ("भस्म", "उज्ज्वल"),
    ("लंका का काल", "लंका में हलचल"),
    ("काल", "तेज"),
    ("जला", "चमका"),
    ("दहन", "प्रकाश"),
)


def _is_rai_blocked_error(err: Exception | str | None) -> bool:
    if not err:
        return False
    text = str(err).lower()
    return (
        "content_blocked" in text
        or "responsible ai" in text
        or "violates google" in text
        or "safety" in text
        or "blocked" in text
    )


def _sanitize_text_for_rai(text: str) -> str:
    out = text or ""
    for src, target in _RAI_REPLACEMENTS:
        out = out.replace(src, target).replace(src.capitalize(), target.capitalize())
    return out


def _sanitize_scene_for_rai(scene, production=None) -> str:
    """Soften intense battle/fire/destruction phrasing into theatrical RAI-safe wording."""
    desc = _sanitize_text_for_rai(scene.visual_description or "")
    suffix = " Theatrical, family-friendly mythological stage drama with warm cinematic lighting."
    if suffix.strip() not in desc:
        desc = desc.rstrip(". ") + "." + suffix
    scene.visual_description = desc

    if getattr(scene, "narration", None):
        narr = scene.narration
        for src, target in _RAI_NARRATION_REPLACEMENTS:
            narr = narr.replace(src, target)
        narr = _sanitize_text_for_rai(narr)
        scene.narration = narr

    if production and getattr(production, "continuity", None):
        if production.continuity.setting_notes:
            production.continuity.setting_notes = _sanitize_text_for_rai(
                production.continuity.setting_notes
            )
        for ch in production.continuity.characters or []:
            if ch.description:
                ch.description = _sanitize_text_for_rai(ch.description)
    return desc


def _merge_frame_usage(
    existing: UsageMetrics | None, added: UsageMetrics
) -> UsageMetrics:
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
    production_id: str, scene, frame_result, frame_position: str = "start"
) -> None:
    """Persist the start or end frame URI + accumulate image cost; mutate the scene object
    so the video step downstream sees both thumbnail_url (start) and end_frame_url (end)."""
    gcs_uri = frame_result.data["image_url"]
    if frame_position == "end":
        scene_updates = {"end_frame_url": gcs_uri}
        if frame_result.data.get("generated_prompt"):
            scene_updates["end_frame_prompt"] = frame_result.data["generated_prompt"]
        scene.end_frame_url = gcs_uri
    else:
        scene_updates = {"thumbnail_url": gcs_uri}
        if frame_result.data.get("generated_prompt"):
            scene_updates["generated_prompt"] = frame_result.data["generated_prompt"]
            scene_updates["image_prompt"] = frame_result.data["generated_prompt"]
        scene.thumbnail_url = gcs_uri

    deps.firestore_svc.update_scene(production_id, scene.id, scene_updates)
    accumulate_image_cost_on(
        "production",
        production_id,
        frame_result.usage.cost_usd,
        input_tokens=frame_result.usage.image_input_tokens,
        output_tokens=frame_result.usage.image_output_tokens,
        model_name=frame_result.usage.image_model_name,
    )
    scene._frame_usage = _merge_frame_usage(
        getattr(scene, "_frame_usage", None), frame_result.usage
    )


async def _call_generate_frame(
    production_id: str,
    scene,
    production,
    frame_position: str = "start",
    start_frame_uri: str | None = None,
):
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


async def _generate_scene_frame(production_id: str, scene, production) -> bool:
    """Generate both START frame (thumbnail_url) and END frame (end_frame_url) for a scene."""
    has_start = bool(scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"))
    has_end = bool(
        getattr(scene, "end_frame_url", None)
        and scene.end_frame_url.startswith("gs://")
    )
    if has_start and has_end:
        scene._frame_usage = None
        return True

    deps.firestore_svc.update_scene(
        production_id, scene.id, {"status": "generating_frame", "error_message": None}
    )

    if not has_start:
        try:
            frame_result = await _call_generate_frame(
                production_id, scene, production, frame_position="start"
            )
        except Exception as e:
            if _is_rai_blocked_error(e):
                logger.warning(
                    f"Start frame hit RAI filter for scene {scene.id}, sanitizing and retrying: {e}"
                )
                sanitized = _sanitize_scene_for_rai(scene)
                deps.firestore_svc.update_scene(
                    production_id, scene.id, {"visual_description": sanitized}
                )
                try:
                    frame_result = await _call_generate_frame(
                        production_id, scene, production, frame_position="start"
                    )
                except Exception as retry_err:
                    logger.error(
                        f"Start frame retry failed for scene {scene.id}: {retry_err}"
                    )
                    _fail_scene(production_id, scene.id, retry_err)
                    return False
            else:
                logger.error(f"Frame generation failed for scene {scene.id}: {e}")
                _fail_scene(production_id, scene.id, e)
                return False

        _record_frame_result(production_id, scene, frame_result, frame_position="start")

    if not has_end and scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
        try:
            end_result = await _call_generate_frame(
                production_id,
                scene,
                production,
                frame_position="end",
                start_frame_uri=scene.thumbnail_url,
            )
            if (
                end_result is not None
                and getattr(end_result, "data", None)
                and end_result.data.get("image_url")
            ):
                _record_frame_result(
                    production_id, scene, end_result, frame_position="end"
                )
        except (TypeError, StopIteration, RuntimeError) as compat_exc:
            logger.debug(
                f"End frame generation skipped for scene {scene.id}: {compat_exc}"
            )
        except Exception as e:
            logger.warning(
                f"End frame generation failed for scene {scene.id}, continuing with start frame: {e}"
            )

    restored_status = (
        "completed"
        if (scene.video_url and scene.video_url.startswith("gs://"))
        else "pending"
    )
    deps.firestore_svc.update_scene(
        production_id,
        scene.id,
        {"status": restored_status, "error_message": None},
    )
    scene.status = restored_status
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
    # Stash resolved video model & resolution on the scene object so _complete_scene_video
    # can cost-account with the correct rate and persist resolution.
    if result.get("model_id"):
        scene._video_model_id = result["model_id"]
    if result.get("resolution"):
        scene._video_resolution = result["resolution"]


async def _generate_scene_video(
    production_id: str,
    scene,
    production,
    quality: str = "draft",
    target_resolution: str = "360p",
):
    """Kick off video generation for a single scene. Returns the result dict
    (or a non-dict for already-generated scenes), or None on failure."""
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
        logger.error(f"Video generation failed for scene {scene.id}: {e}")
        scene._last_video_error = str(e)
        _fail_scene(production_id, scene.id, e)
        return None

    if isinstance(result, dict):
        _persist_video_result(production_id, scene, result)
    return result


def _complete_scene_video(
    production_id: str,
    scene,
    video_uri: str,
    video_resolution: str | None = None,
) -> None:
    """Persist completed scene video URI + resolution and accumulate video cost."""
    resolved_res = (
        video_resolution
        or getattr(scene, "_video_resolution", None)
        or getattr(scene, "video_resolution", None)
        or "360p"
    )
    deps.firestore_svc.update_scene(
        production_id,
        scene.id,
        {
            "status": "completed",
            "video_url": video_uri,
            "video_resolution": resolved_res,
            "error_message": None,
        },
    )
    scene.video_url = video_uri
    scene.video_resolution = resolved_res
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
    production_id: str, scene, target_resolution: str | None = None
) -> bool:
    """Poll a scene's video operation until complete. Returns True on success."""
    op_name = getattr(scene, "_pending_op", None)
    if not op_name:
        return True

    veo_status = await _poll_veo_operation(op_name)
    if veo_status.get("status") == "completed" and veo_status.get("video_uri"):
        _complete_scene_video(
            production_id, scene, veo_status["video_uri"], target_resolution
        )
        return True

    error = veo_status.get("error") or veo_status.get(
        "message", "Video generation failed"
    )
    scene._last_video_error = str(error)
    logger.error(f"Veo failed for scene {scene.id}: {error}")
    _fail_scene(production_id, scene.id, error)
    return False


def _scene_has_valid_video(scene, quality: str, target_resolution: str) -> bool:
    """Determine if a scene's existing video can be reused without re-generating."""
    if not scene.video_url or not scene.video_url.startswith("gs://"):
        return False
    return scene.video_resolution == target_resolution or (
        quality == "draft" and bool(scene.video_url)
    )


def _aggregate_frame_usage(scenes) -> tuple[UsageMetrics, int]:
    """Sum UsageMetrics across scenes that generated new keyframes."""
    gen_count = 0
    in_tok = 0
    out_tok = 0
    cost = 0.0
    model_name = ""
    for s in scenes:
        u = getattr(s, "_frame_usage", None)
        if u is not None:
            gen_count += max(1, u.image_generations)
            in_tok += u.image_input_tokens
            out_tok += u.image_output_tokens
            cost += u.cost_usd
            if u.image_model_name:
                model_name = u.image_model_name
    return (
        UsageMetrics(
            image_generations=gen_count,
            image_input_tokens=in_tok,
            image_output_tokens=out_tok,
            image_model_name=model_name,
            image_cost_usd=cost,
            cost_usd=cost,
        ),
        gen_count,
    )


def _aggregate_video_usage(scenes) -> tuple[UsageMetrics, int]:
    """Sum UsageMetrics across scenes that generated new video clips."""
    vid_count = 0
    vid_seconds = 0
    cost = 0.0
    unit_cost = 0.0
    model_id = ""
    for s in scenes:
        u = getattr(s, "_video_usage", None)
        if u is not None:
            vid_count += max(1, u.veo_videos)
            vid_seconds += u.veo_seconds
            cost += u.cost_usd
            if u.veo_unit_cost:
                unit_cost = u.veo_unit_cost
            if u.veo_model_id:
                model_id = u.veo_model_id
    return (
        UsageMetrics(
            veo_videos=vid_count,
            veo_seconds=vid_seconds,
            veo_model_id=model_id,
            veo_unit_cost=unit_cost,
            veo_cost_usd=cost,
            cost_usd=cost,
        ),
        vid_count,
    )


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


def _compute_stitch_usage(
    production_id: str, production, resolution: str = "720p"
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
    production,
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
            logger.info(f"Production {production_id} completed successfully")
            return True
        if state in ("FAILED", "UNKNOWN"):
            logger.warning(f"Transcoder job {job_name} ended with state {state}")
            return False


def _ffmpeg_stitch_scenes(
    production_id: str,
    scene_uris: list[str],
    orientation: str = "16:9",
    resolution: str = "720p",
) -> str:
    """Download scene clips, normalize in parallel, concatenate, and upload to GCS."""
    bucket = os.getenv("GCS_BUCKET", "aug18-25-3-veo-generators-media")
    if resolution == "360p":
        mux_name = "draft.mp4"
        base_w, base_h = 640, 360
    elif resolution == "1080p":
        mux_name = "final.mp4"
        base_w, base_h = 1920, 1080
    else:
        mux_name = "final.mp4"
        base_w, base_h = 1280, 720

    output_uri = f"gs://{bucket}/productions/{production_id}/stitched/{mux_name}"
    width, height = (base_h, base_w) if orientation == "9:16" else (base_w, base_h)

    temp_files: list[str] = []
    try:
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
                pool.submit(normalize_segment, raw_p, norm_p, width, height)
                for raw_p, norm_p in zip(raw_paths, norm_paths)
            ]
            for fut in futures:
                fut.result()

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


async def _stitch_production(
    production_id: str,
    production,
    quality: str = "final",
    resolution: str = "720p",
    steps: list[dict] | None = None,
) -> str | None:
    """Combine all scene videos into a final/draft video via Transcoder (with FFmpeg fallback)."""
    scene_uris = _collect_scene_uris(production_id, production)
    if scene_uris is None:
        if steps is not None:
            _update_pipeline_step(
                production_id, steps, "stitch_video", "failed", "Missing scene video"
            )
        return None

    if steps is not None:
        _update_pipeline_step(
            production_id,
            steps,
            "stitch_video",
            "running",
            f"Stitching {len(scene_uris)} scene clips at {resolution}...",
            extra_updates={"status": ProjectStatus.STITCHING, "error_message": None},
        )
    else:
        deps.firestore_svc.update_production(
            production_id, {"status": ProjectStatus.STITCHING, "error_message": None}
        )

    is_draft = quality == "draft" or resolution == "360p"
    tier = TRANSCODER_SD if resolution == "360p" else TRANSCODER_HD
    total_seconds = sum(_scene_duration_seconds(s) for s in production.scenes)
    minutes = total_seconds / 60.0
    tier_id = tier.id.replace("transcoder_", "")
    stitch_cost = minutes * tier.unit_cost_usd
    stitch_usage = UsageMetrics(
        transcoder_minutes=minutes,
        transcoder_tier=tier_id,
        transcoder_cost_usd=stitch_cost,
        cost_usd=stitch_cost,
    )

    transcoder_ok = False
    final_uri: str | None = None
    if deps.transcoder_svc:
        try:
            try:
                job_name, final_uri = await asyncio.to_thread(
                    deps.transcoder_svc.stitch_from_uris,
                    production_id,
                    scene_uris,
                    orientation=production.orientation,
                    resolution=resolution,
                )
            except TypeError:
                job_name, final_uri = await asyncio.to_thread(
                    deps.transcoder_svc.stitch_from_uris,
                    production_id,
                    scene_uris,
                    orientation=production.orientation,
                )
            url_updates: dict = {
                "stitch_job_name": job_name,
                "final_video_url": final_uri,
            }
            if is_draft:
                url_updates["draft_video_url"] = final_uri
            deps.firestore_svc.update_production(production_id, url_updates)
            try:
                transcoder_ok = await _wait_for_stitch(
                    production_id,
                    production,
                    job_name,
                    resolution=resolution,
                )
            except TypeError:
                transcoder_ok = await _wait_for_stitch(
                    production_id, production, job_name
                )
        except Exception as e:
            logger.warning(
                f"Cloud Transcoder stitch failed for {production_id}, trying FFmpeg fallback: {e}"
            )

    if transcoder_ok and final_uri:
        if steps is not None:
            _update_pipeline_step(
                production_id,
                steps,
                "stitch_video",
                "completed",
                f"Stitched {len(scene_uris)} clips ({resolution}) • {minutes:.2f} min (${stitch_cost:.4f})",
                usage=stitch_usage,
            )
        return final_uri

    if not deps.storage_svc:
        if steps is not None:
            _update_pipeline_step(
                production_id,
                steps,
                "stitch_video",
                "failed",
                "Transcoder stitch failed and storage unavailable",
            )
        _fail_production(
            production_id, "Transcoder stitch failed and storage unavailable"
        )
        return None

    try:
        logger.info(f"Running FFmpeg stitch fallback for production {production_id}")
        try:
            final_uri = await asyncio.to_thread(
                _ffmpeg_stitch_scenes,
                production_id,
                scene_uris,
                production.orientation or "16:9",
                resolution,
            )
        except TypeError:
            final_uri = await asyncio.to_thread(
                _ffmpeg_stitch_scenes,
                production_id,
                scene_uris,
                production.orientation or "16:9",
            )
        url_updates = {
            "status": ProjectStatus.COMPLETED,
            "final_video_url": final_uri,
            "error_message": None,
        }
        if is_draft:
            url_updates["draft_video_url"] = final_uri
        deps.firestore_svc.update_production(production_id, url_updates)
        if steps is not None:
            _update_pipeline_step(
                production_id,
                steps,
                "stitch_video",
                "completed",
                f"Stitched {len(scene_uris)} clips via FFmpeg ({resolution})",
                usage=UsageMetrics(),
            )
        logger.info(f"Production {production_id} stitched via FFmpeg: {final_uri}")
        return final_uri
    except Exception as e:
        logger.error(f"FFmpeg stitch fallback failed for {production_id}: {e}")
        if steps is not None:
            _update_pipeline_step(
                production_id, steps, "stitch_video", "failed", str(e)
            )
        _fail_production(production_id, f"Stitching failed: {e}")
        return None


async def _attempt_scene_video(
    production_id: str,
    scene,
    production,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
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
    return True


async def _run_scene_video_stage(
    production_id: str,
    scene,
    production,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Kick off and poll video generation for a single scene, with automatic
    Responsible AI (content_blocked) prompt sanitization & retry."""
    scene._last_video_error = None
    ok = await _attempt_scene_video(
        production_id,
        scene,
        production,
        quality=quality,
        target_resolution=target_resolution,
    )
    if ok:
        return True

    last_err = getattr(scene, "_last_video_error", None)
    if not _is_rai_blocked_error(last_err):
        return False

    logger.warning(
        f"Scene {scene.id} hit Responsible AI filter ({last_err}); sanitizing prompt and retrying..."
    )
    sanitized_desc = _sanitize_scene_for_rai(scene, production=production)
    scene_upd: dict = {
        "visual_description": sanitized_desc,
        "status": "generating",
        "error_message": None,
    }
    if getattr(scene, "narration", None) is not None:
        scene_upd["narration"] = scene.narration
    deps.firestore_svc.update_scene(
        production_id,
        scene.id,
        scene_upd,
    )
    scene._last_video_error = None
    retry_ok = await _attempt_scene_video(
        production_id,
        scene,
        production,
        quality=quality,
        target_resolution=target_resolution,
    )
    if retry_ok:
        return True

    # If the reference image itself triggered Responsible AI, retry once in text-to-video mode
    saved_start = scene.thumbnail_url
    saved_end = getattr(scene, "end_frame_url", None)
    if _is_rai_blocked_error(getattr(scene, "_last_video_error", None)) and (
        saved_start or saved_end
    ):
        logger.warning(
            f"Scene {scene.id} still blocked with keyframe image; retrying text-to-video fallback..."
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
    return False


async def _run_frame_phase_for_scene(
    production_id: str,
    scene,
    production,
    image_sem: asyncio.Semaphore | None = None,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Phase 2A per-scene worker: generate start & end frames for each scene."""
    scene._frame_usage = None
    scene._video_usage = None
    if image_sem is not None:
        async with image_sem:
            return await _generate_scene_frame(production_id, scene, production)
    return await _generate_scene_frame(production_id, scene, production)


async def _run_video_phase_for_scene(
    production_id: str,
    scene,
    production,
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
    scene,
    production,
    image_sem: asyncio.Semaphore | None = None,
    video_sem: asyncio.Semaphore | None = None,
    quality: str = "draft",
    target_resolution: str = "360p",
) -> bool:
    """Run frame → video → poll for a single scene using bounded semaphores."""
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


async def run_storyboard_review_step(
    production_id: str,
    production=None,
    steps: list[dict] | None = None,
):
    """Stage 1: Audit storyboard continuity, speaker attribution, and prop physics."""
    if production is None:
        production = deps.firestore_svc.get_production(production_id)
    if not production:
        return None
    if steps is None:
        steps = _ensure_steps_list(production, auto_review=True)

    _update_pipeline_step(
        production_id,
        steps,
        "review_storyboard",
        "running",
        "Auditing storyboard continuity, speaker lip-sync & physics...",
        extra_updates={"status": ProjectStatus.REVIEWING},
    )
    res = await deps.ai_svc.review_storyboard(production_id, production)
    accumulate_text_cost_on(
        "production",
        production_id,
        res.usage.cost_usd,
        res.usage.input_tokens,
        res.usage.output_tokens,
        res.usage.model_name,
    )
    report = res.data["review_report"]
    continuity = res.data.get("continuity")
    scenes = res.data.get("scenes") or production.scenes

    production.scenes = scenes
    if continuity is not None:
        production.continuity = continuity
    production.review_report = report

    extra: dict = {
        "scenes": [s.dict() for s in scenes],
        "review_report": report.dict(),
    }
    if continuity is not None:
        extra["continuity"] = continuity.dict()

    detail = (
        f"Score {report.overall_score}/100 • Fixed {len(report.issues)} issue(s) • "
        f"{res.usage.input_tokens:,} in / {res.usage.output_tokens:,} out tokens "
        f"(${res.usage.cost_usd:.4f})"
    )
    _update_pipeline_step(
        production_id,
        steps,
        "review_storyboard",
        "completed",
        detail=detail,
        usage=res.usage,
        extra_updates=extra,
    )
    return res


async def run_video_eval_step(
    production_id: str,
    production=None,
    stitched_uri: str | None = None,
    iteration: int = 1,
    steps: list[dict] | None = None,
):
    """Stage 4: Multimodal evaluation of the finished stitched video against the storyboard."""
    if production is None:
        production = deps.firestore_svc.get_production(production_id)
    if not production:
        return None
    if steps is None:
        steps = _ensure_steps_list(production, auto_eval=True)

    _update_pipeline_step(
        production_id,
        steps,
        "evaluate_video",
        "running",
        "Evaluating finished video for continuity, lip-sync & physical realism...",
        extra_updates={"status": ProjectStatus.EVALUATING},
    )
    eval_res = await deps.ai_svc.evaluate_finished_video(
        production_id,
        production,
        video_gcs_uri=stitched_uri,
        iteration=iteration,
    )
    accumulate_text_cost_on(
        "production",
        production_id,
        eval_res.usage.cost_usd,
        eval_res.usage.input_tokens,
        eval_res.usage.output_tokens,
        eval_res.usage.model_name,
    )
    eval_report = eval_res.data["eval_report"]

    findings_by_scene: dict[str, object] = {}
    for idx, scene in enumerate(production.scenes):
        matched = next(
            (
                f
                for f in eval_report.findings
                if f.scene_id == scene.id or f.scene_number == idx + 1
            ),
            None,
        )
        if matched is not None:
            scene.eval_status = "flagged"
            scene.eval_feedback = matched.observed_issue
            findings_by_scene[scene.id] = matched
        else:
            scene.eval_status = "passed"

    production.eval_report = eval_report
    status_str = (
        "PASSED"
        if eval_report.passed
        else f"Flagged {len(eval_report.findings)} scene(s)"
    )
    detail = (
        f"Score {eval_report.overall_score}/100 ({status_str}) • "
        f"{eval_res.usage.input_tokens:,} in / {eval_res.usage.output_tokens:,} out tokens "
        f"(${eval_res.usage.cost_usd:.4f})"
    )
    _update_pipeline_step(
        production_id,
        steps,
        "evaluate_video",
        "completed",
        detail=detail,
        usage=eval_res.usage,
        extra_updates={
            "scenes": [s.dict() for s in production.scenes],
            "eval_report": eval_report.dict(),
        },
    )
    return eval_report


async def run_selective_regenerate_step(
    production_id: str,
    production=None,
    eval_report=None,
    quality: str = "draft",
    target_resolution: str = "360p",
    steps: list[dict] | None = None,
) -> bool:
    """Stage 5: Apply corrective prompt updates to flagged scenes, re-render frames then videos, and re-stitch."""
    if production is None:
        production = deps.firestore_svc.get_production(production_id)
    if not production:
        return False
    if eval_report is None:
        eval_report = production.eval_report
    if not eval_report or not eval_report.findings:
        return True
    if steps is None:
        steps = _ensure_steps_list(production, auto_eval=True)

    flagged_scenes = []
    for idx, scene in enumerate(production.scenes):
        finding = next(
            (
                f
                for f in eval_report.findings
                if f.scene_id == scene.id or f.scene_number == idx + 1
            ),
            None,
        )
        if finding is None:
            continue
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
        flagged_scenes.append(scene)

    if not flagged_scenes:
        _update_pipeline_step(
            production_id,
            steps,
            "regenerate_scenes",
            "skipped",
            "No scenes required regeneration",
        )
        return True

    _update_pipeline_step(
        production_id,
        steps,
        "regenerate_scenes",
        "running",
        f"Regenerating keyframes & videos for {len(flagged_scenes)} flagged scene(s)...",
        extra_updates={
            "status": ProjectStatus.REGENERATING,
            "scenes": [s.dict() for s in production.scenes],
        },
    )

    image_sem = asyncio.Semaphore(_image_concurrency())
    video_sem = asyncio.Semaphore(_video_concurrency())

    # Phase 5A: Regenerate start & end frames first for all flagged scenes
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
    failed_ids = []
    for s, outcome in zip(flagged_scenes, frame_results):
        if isinstance(outcome, Exception):
            logger.error(f"Regeneration frame failed for scene {s.id}: {outcome}")
            _fail_scene(production_id, s.id, outcome)
            failed_ids.append(s.id)
        elif not outcome:
            failed_ids.append(s.id)

    # Phase 5B: Only after keyframes are ready, regenerate videos for flagged scenes
    if not failed_ids:
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
        for s, outcome in zip(flagged_scenes, video_results):
            if isinstance(outcome, Exception):
                logger.error(f"Regeneration video failed for scene {s.id}: {outcome}")
                _fail_scene(production_id, s.id, outcome)
                failed_ids.append(s.id)
            elif not outcome:
                failed_ids.append(s.id)

    if failed_ids:
        _update_pipeline_step(
            production_id,
            steps,
            "regenerate_scenes",
            "failed",
            f"Regeneration failed for scene(s): {', '.join(failed_ids)}",
        )
        _fail_production(
            production_id,
            f"Selective regeneration failed for scene(s): {', '.join(failed_ids)}",
        )
        return False

    frame_usage, regen_frames = _aggregate_frame_usage(flagged_scenes)
    video_usage, regen_videos = _aggregate_video_usage(flagged_scenes)

    refreshed_prod = deps.firestore_svc.get_production(production_id) or production
    restitched_uri = await _stitch_production(
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

    tier = TRANSCODER_SD if target_resolution == "360p" else TRANSCODER_HD
    total_seconds = sum(_scene_duration_seconds(s) for s in refreshed_prod.scenes)
    minutes = total_seconds / 60.0
    transcoder_cost = minutes * tier.unit_cost_usd
    total_regen_cost = frame_usage.cost_usd + video_usage.cost_usd + transcoder_cost
    combined_usage = UsageMetrics(
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
    _update_pipeline_step(
        production_id,
        steps,
        "regenerate_scenes",
        "completed",
        detail=detail,
        usage=combined_usage,
        extra_updates={
            "scenes": [s.dict() for s in refreshed_prod.scenes],
            "eval_report": eval_report.dict(),
        },
    )
    return True


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

    effective_quality = (
        quality or getattr(production, "render_quality", None) or "draft"
    )
    if effective_quality == "draft":
        target_resolution = resolution or "360p"
    else:
        raw_res = resolution or getattr(production, "video_resolution", None) or "720p"
        target_resolution = "720p" if raw_res == "360p" else raw_res

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

    image_sem = asyncio.Semaphore(_image_concurrency())
    video_sem = asyncio.Semaphore(_video_concurrency())

    try:
        # Stage 1: Storyboard Continuity & Realism Review
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

        # Stage 2A: Start & End Keyframe Generation (must complete BEFORE video generation)
        _update_pipeline_step(
            production_id,
            steps,
            "generate_frames",
            "running",
            f"Generating start & end keyframes across {len(production.scenes)} scene(s)...",
            extra_updates={"status": ProjectStatus.GENERATING},
        )

        frame_results = await asyncio.gather(
            *(
                _run_frame_phase_for_scene(
                    production_id,
                    scene,
                    production,
                    image_sem=image_sem,
                    quality=effective_quality,
                    target_resolution=target_resolution,
                )
                for scene in production.scenes
            ),
            return_exceptions=True,
        )

        failed_frame_scenes = []
        for scene, outcome in zip(production.scenes, frame_results):
            if isinstance(outcome, Exception):
                logger.error(
                    f"Scene {scene.id} frame phase raised unhandled error: {outcome}"
                )
                _fail_scene(production_id, scene.id, outcome)
                failed_frame_scenes.append(scene.id)
            elif not outcome:
                failed_frame_scenes.append(scene.id)

        if failed_frame_scenes:
            _update_pipeline_step(
                production_id,
                steps,
                "generate_frames",
                "failed",
                f"Keyframe generation failed for scene(s): {', '.join(failed_frame_scenes)}",
            )
            _fail_production(
                production_id,
                f"Keyframe generation failed for scene(s): {', '.join(failed_frame_scenes)}",
                steps=steps,
            )
            return

        frame_usage, gen_frames = _aggregate_frame_usage(production.scenes)
        scenes_with_new_frames = sum(
            1 for s in production.scenes if getattr(s, "_frame_usage", None) is not None
        )
        reused_frame_scenes = len(production.scenes) - scenes_with_new_frames
        frame_detail = (
            f"Generated {gen_frames} start/end frame(s)"
            + (
                f", reused {reused_frame_scenes} scene(s)"
                if reused_frame_scenes
                else ""
            )
            + f" • {frame_usage.image_input_tokens:,} in / {frame_usage.image_output_tokens:,} out tokens (${frame_usage.cost_usd:.4f})"
        )
        _update_pipeline_step(
            production_id,
            steps,
            "generate_frames",
            "completed",
            detail=frame_detail,
            usage=frame_usage,
        )

        # Stage 2B: Scene Video Generation (uses completed Start & End keyframes as inputs)
        _update_pipeline_step(
            production_id,
            steps,
            "generate_videos",
            "running",
            f"Generating {target_resolution} ({effective_quality}) videos from start & end frames...",
            extra_updates={"status": ProjectStatus.GENERATING},
        )

        video_results = await asyncio.gather(
            *(
                _run_video_phase_for_scene(
                    production_id,
                    scene,
                    production,
                    video_sem=video_sem,
                    quality=effective_quality,
                    target_resolution=target_resolution,
                )
                for scene in production.scenes
            ),
            return_exceptions=True,
        )

        failed_scenes = []
        for scene, outcome in zip(production.scenes, video_results):
            if isinstance(outcome, Exception):
                logger.error(f"Scene {scene.id} raised unhandled error: {outcome}")
                _fail_scene(production_id, scene.id, outcome)
                failed_scenes.append(scene.id)
            elif not outcome:
                failed_scenes.append(scene.id)

        if failed_scenes:
            _update_pipeline_step(
                production_id,
                steps,
                "generate_videos",
                "failed",
                f"Generation failed for scene(s): {', '.join(failed_scenes)}",
            )
            _fail_production(
                production_id,
                f"Generation failed for scene(s): {', '.join(failed_scenes)}",
                steps=steps,
            )
            return

        video_usage, gen_videos = _aggregate_video_usage(production.scenes)
        reused_videos = len(production.scenes) - gen_videos
        video_detail = (
            f"Generated {gen_videos} clip(s) at {target_resolution}"
            + (f", reused {reused_videos}" if reused_videos else "")
            + f" • {video_usage.veo_seconds}s (${video_usage.cost_usd:.4f})"
        )
        _update_pipeline_step(
            production_id,
            steps,
            "generate_videos",
            "completed",
            detail=video_detail,
            usage=video_usage,
        )

        # Stage 3: Video Transcoding & Stitching
        production = deps.firestore_svc.get_production(production_id) or production
        stitched_uri = await _stitch_production(
            production_id,
            production,
            quality=effective_quality,
            resolution=target_resolution,
            steps=steps,
        )
        if not stitched_uri:
            return

        # Stage 4: Multimodal Finished-Video Evaluation
        production = deps.firestore_svc.get_production(production_id) or production
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

        # Stage 5: Selective Auto-Regeneration & Re-Stitch
        if (
            auto_eval
            and eval_report is not None
            and not eval_report.passed
            and eval_report.findings
            and max_eval_iterations > 0
        ):
            regen_ok = await run_selective_regenerate_step(
                production_id,
                production=production,
                eval_report=eval_report,
                quality=effective_quality,
                target_resolution=target_resolution,
                steps=steps,
            )
            if not regen_ok:
                return
        else:
            skip_msg = (
                "All scenes passed evaluation"
                if (eval_report and eval_report.passed)
                else "Skipped selective regeneration"
            )
            _update_pipeline_step(
                production_id,
                steps,
                "regenerate_scenes",
                "skipped",
                skip_msg,
            )

        deps.firestore_svc.update_production(
            production_id,
            {
                "status": ProjectStatus.COMPLETED,
                "pipeline_stage": "completed",
                "pipeline_steps": steps,
                "error_message": None,
            },
        )
    except Exception as e:
        logger.error(f"Render failed for {production_id}: {e}")
        _fail_production(production_id, str(e), steps=steps)

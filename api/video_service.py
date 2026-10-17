import asyncio
import logging
import os
import zlib
from typing import Any, Optional

from google import genai
from google.genai import types

from helpers import sdk_call_with_retry
from models import Project, Scene
from prompt_templates import VEO_NEGATIVE_PROMPT
from video_prompt_helpers import (  # noqa: F401
    _build_omni_inputs,
    _is_omni_model,
    _log_ctx,
    _resolve_model_and_resolution,
    _resolve_ref_urls,
    build_scene_video_prompt,
    extract_omni_video_uri,
)

logger = logging.getLogger(__name__)


class VideoService:
    def __init__(self, storage_svc: Any = None, firestore_svc: Any = None) -> None:
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.veo_location = os.getenv("VEO_REGION", "global")
        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc
        self.video_client = genai.Client(
            vertexai=True, project=self.project_id, location=self.veo_location
        )
        self._clients: dict[str, genai.Client] = {self.veo_location: self.video_client}

    def _get_client(self, region: str | None = None) -> genai.Client:
        loc = region or self.veo_location
        if loc not in self._clients:
            self._clients[loc] = genai.Client(
                vertexai=True, project=self.project_id, location=loc
            )
        return self._clients[loc]

    def _get_project_seed(self, project_id: str) -> int:
        return zlib.adler32(project_id.encode()) & 0x7FFFFFFF

    def _parse_timestamp(self, ts: str) -> float:
        """Parse '00:05' or '5' to seconds."""
        if ":" in ts:
            parts = ts.split(":")
            return int(parts[0]) * 60 + float(parts[1])
        return float(ts)

    def _build_video_prompt(
        self, scene: Scene, project: Optional[Project], duration: int
    ) -> str:
        """Build a video-specific prompt with duration and camera movement."""
        return build_scene_video_prompt(scene, project, duration)

    def _extract_omni_video_uri(
        self, interaction: Any, name_hint: str
    ) -> Optional[str]:
        """Extract a gs:// URI from a completed Gemini Omni interaction."""
        return extract_omni_video_uri(interaction, name_hint, self.storage_svc)

    def _compute_scene_duration(self, scene: Scene, is_omni: bool) -> int:
        supported_durations = list(range(3, 11)) if is_omni else [4, 6, 8]
        try:
            start = self._parse_timestamp(scene.timestamp_start)
            end = self._parse_timestamp(scene.timestamp_end)
            raw = int(end - start)
            return min(supported_durations, key=lambda d: abs(d - raw))
        except (ValueError, IndexError):
            return 8

    async def _generate_omni_video(
        self,
        client: Any,
        model_id: str,
        project_id: str,
        project: Optional[Project],
        enriched_prompt: str,
        ref_url: Optional[str],
        end_ref_url: Optional[str],
        duration: int,
        effective_resolution: str,
        blocking: bool,
    ) -> dict[str, Any]:
        input_blocks, video_task, fmt_block = _build_omni_inputs(
            enriched_prompt,
            ref_url,
            end_ref_url,
            project,
            effective_resolution,
            duration,
            project_id,
        )
        gen_cfg = {"video_config": {"task": video_task}}
        try:
            interaction = await sdk_call_with_retry(
                client.interactions.create,
                model=model_id,
                background=not blocking,
                input=input_blocks,
                response_format=[fmt_block],
                generation_config=gen_cfg,
            )
        except Exception:
            if not (end_ref_url and len(input_blocks) > 2):
                raise
            interaction = await sdk_call_with_retry(
                client.interactions.create,
                model=model_id,
                background=not blocking,
                input=input_blocks[:2],
                response_format=[fmt_block],
                generation_config=gen_cfg,
            )
        interaction_id = getattr(interaction, "id", None) or (
            interaction.get("id") if isinstance(interaction, dict) else ""
        )
        base_res = {
            "generated_prompt": enriched_prompt,
            "model_id": model_id,
            "duration_seconds": duration,
            "resolution": effective_resolution,
        }
        if not blocking:
            return {
                "operation_name": f"interaction:{interaction_id}",
                "status": "processing",
                **base_res,
            }
        while getattr(interaction, "status", None) in ("in_progress", "queued"):
            await asyncio.sleep(10)
            interaction = await asyncio.to_thread(
                client.interactions.get, interaction_id
            )
        return {
            "video_uri": self._extract_omni_video_uri(
                interaction, interaction_id or project_id
            )
            or "",
            **base_res,
        }

    async def _generate_veo_video(
        self,
        client: Any,
        model_id: str,
        seed: int,
        project: Optional[Project],
        enriched_prompt: str,
        ref_url: Optional[str],
        end_ref_url: Optional[str],
        duration: int,
        effective_resolution: str,
        blocking: bool,
    ) -> dict[str, Any]:
        veo_res = (
            effective_resolution
            if effective_resolution in ("720p", "1080p", "4k")
            else "720p"
        )
        config_kwargs: dict = {
            "duration_seconds": duration,
            "seed": seed,
            "aspect_ratio": project.orientation if project else "16:9",
            "number_of_videos": 1,
            "generate_audio": True,
            "person_generation": "allow_all",
            "resolution": veo_res,
            "negative_prompt": VEO_NEGATIVE_PROMPT,
        }
        if end_ref_url and end_ref_url.startswith("gs://"):
            config_kwargs["last_frame"] = types.Image(
                gcs_uri=end_ref_url, mime_type="image/png"
            )
        generate_kwargs: dict = {
            "model": model_id,
            "prompt": enriched_prompt,
            "config": types.GenerateVideosConfig(**config_kwargs),
        }
        if ref_url and ref_url.startswith("gs://"):
            generate_kwargs["image"] = types.Image(
                gcs_uri=ref_url, mime_type="image/png"
            )
        operation = await sdk_call_with_retry(
            client.models.generate_videos, **generate_kwargs
        )
        base_res = {
            "generated_prompt": enriched_prompt,
            "model_id": model_id,
            "duration_seconds": duration,
            "resolution": veo_res,
        }
        if not blocking:
            return {
                "operation_name": operation.name,
                "status": "processing",
                **base_res,
            }
        while not operation.done:
            await asyncio.sleep(10)
        uri = (
            operation.result.generated_videos[0].video.uri
            if operation.result and operation.result.generated_videos
            else ""
        )
        return {"video_uri": uri, **base_res}

    async def generate_scene_video(
        self,
        project_id: str,
        scene: Scene,
        blocking: bool = True,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        resolution: Optional[str] = None,
        render_quality: Optional[str] = None,
    ) -> dict[str, Any]:
        resolved_model, effective_resolution = _resolve_model_and_resolution(
            self.firestore_svc, project, model_id, resolution, render_quality
        )
        is_omni = _is_omni_model(resolved_model)
        client = self._get_client("global" if is_omni else region)
        seed = self._get_project_seed(project_id)
        duration = self._compute_scene_duration(scene, is_omni)
        enriched_prompt = prompt_override or self._build_video_prompt(
            scene, project, duration
        )
        ref_url, end_ref_url = _resolve_ref_urls(scene, project)
        if ref_url and end_ref_url:
            enriched_prompt = (
                f"{enriched_prompt} "
                f"Start-to-End Keyframe Guidance: Begin from the provided START frame (0s) "
                f"and smoothly progress the continuous action to arrive at the provided END frame ({duration}s)."
            )
        if is_omni:
            return await self._generate_omni_video(
                client,
                resolved_model,
                project_id,
                project,
                enriched_prompt,
                ref_url,
                end_ref_url,
                duration,
                effective_resolution,
                blocking,
            )
        return await self._generate_veo_video(
            client,
            resolved_model,
            seed,
            project,
            enriched_prompt,
            ref_url,
            end_ref_url,
            duration,
            effective_resolution,
            blocking,
        )

    async def _check_omni_interaction_status(
        self, operation_name: str
    ) -> dict[str, Any]:
        interaction_id = operation_name.split("interaction:", 1)[1]
        client = self._get_client("global")
        interaction = await asyncio.to_thread(client.interactions.get, interaction_id)
        status = getattr(interaction, "status", None) or (
            interaction.get("status") if isinstance(interaction, dict) else None
        )
        if status in ("in_progress", "queued", None):
            return {"status": "processing"}
        if status in ("failed", "cancelled", "incomplete", "budget_exceeded"):
            errors = getattr(interaction, "errors", None) or (
                interaction.get("errors") if isinstance(interaction, dict) else None
            )
            return {"status": "failed", "error": str(errors or status)}
        if status == "completed":
            uri = self._extract_omni_video_uri(interaction, interaction_id)
            if uri:
                logger.info(
                    f"Video generated (Gemini Omni): {uri}",
                    extra=_log_ctx("get_video_generation_status", "omni_completed"),
                )
                return {"status": "completed", "video_uri": uri}
            logger.warning(
                "Interaction complete but no video found in result.",
                extra=_log_ctx("get_video_generation_status", "omni_empty"),
            )
            return {"status": "completed", "video_uri": None}
        return {"status": "processing"}

    def _extract_veo_result_uri(
        self, first_video: Any, operation_name: str
    ) -> Optional[str]:
        uri = (
            getattr(first_video.video, "uri", None)
            if hasattr(first_video, "video")
            else None
        )
        if not uri:
            video_bytes = (
                getattr(first_video.video, "video_bytes", None)
                if hasattr(first_video, "video")
                else None
            )
            if video_bytes and self.storage_svc:
                filename = f"videos/{operation_name.replace('/', '_')}.mp4"
                logger.info(
                    f"Uploading raw video bytes to {filename}...",
                    extra=_log_ctx("_extract_veo_result_uri", "upload_bytes"),
                )
                uri = self.storage_svc.upload_bytes(
                    video_bytes, filename, content_type="video/mp4"
                )
        if uri is None and isinstance(first_video, dict):
            video_obj = first_video.get("video")
            uri = (
                video_obj.get("uri")
                if isinstance(video_obj, dict)
                else getattr(video_obj, "uri", None)
            )
        return uri

    def _parse_completed_veo_operation(
        self, operation: Any, operation_name: str
    ) -> dict[str, Any]:
        error = getattr(operation, "error", None)
        if error is None and isinstance(operation, dict):
            error = operation.get("error")
        if error:
            logger.error(
                f"Operation failed: {error}",
                extra=_log_ctx("get_video_generation_status", "veo_failed"),
            )
            return {"status": "failed", "error": str(error)}
        result = getattr(operation, "result", None) or (
            operation.get("result") if isinstance(operation, dict) else None
        )
        if result:
            videos = getattr(result, "generated_videos", None) or (
                result.get("generated_videos") if isinstance(result, dict) else None
            )
            if videos:
                uri = self._extract_veo_result_uri(videos[0], operation_name)
                if uri:
                    logger.info(
                        f"Video generated: {uri}",
                        extra=_log_ctx("get_video_generation_status", "veo_completed"),
                    )
                    return {"status": "completed", "video_uri": uri}
        logger.warning(
            "Operation complete but no video found in result.",
            extra=_log_ctx("get_video_generation_status", "veo_empty"),
        )
        return {"status": "completed", "video_uri": None}

    async def get_video_generation_status(self, operation_name: str) -> dict[str, Any]:
        try:
            logger.info(
                f"Checking operation: {operation_name}",
                extra=_log_ctx("get_video_generation_status", "check_status"),
            )
            if operation_name.startswith("interaction:"):
                return await self._check_omni_interaction_status(operation_name)
            operation_wrapper = types.GenerateVideosOperation(name=operation_name)
            operation = await asyncio.to_thread(
                self.video_client.operations.get, operation_wrapper
            )
            is_done = getattr(operation, "done", None)
            if is_done is None and isinstance(operation, dict):
                is_done = operation.get("done")
            if is_done:
                return self._parse_completed_veo_operation(operation, operation_name)
            return {"status": "processing"}
        except Exception as e:
            logger.error(
                f"Error checking status: {e}",
                exc_info=True,
                extra=_log_ctx("get_video_generation_status", "status_error"),
            )
            return {"status": "error", "message": str(e)}

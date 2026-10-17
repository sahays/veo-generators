"""Vertex AI VideoGenerator adapter (`gemini-omni-1.1-flash-preview` / Veo)."""

from __future__ import annotations

import base64
import logging
import os
import time
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types

from ..compile import Package
from ..config import VideoProviderCfg
from ..errors import StoryGraphError

logger = logging.getLogger(__name__)


def _extract_omni_video_payload(interaction: Any) -> tuple[str | None, bytes | None]:
    """Return (gcs_uri, raw_video_bytes) from a completed Gemini Omni interaction."""
    output_video = getattr(interaction, "output_video", None)
    if output_video is None and isinstance(interaction, dict):
        output_video = interaction.get("output_video")

    if output_video is None:
        steps = getattr(interaction, "steps", None)
        if steps is None and isinstance(interaction, dict):
            steps = interaction.get("steps")
        for step in reversed(steps or []):
            step_type = (
                step.get("type")
                if isinstance(step, dict)
                else getattr(step, "type", None)
            )
            if step_type != "model_output":
                continue
            content = (
                step.get("content")
                if isinstance(step, dict)
                else getattr(step, "content", None)
            )
            for item in reversed(content or []):
                item_type = (
                    item.get("type")
                    if isinstance(item, dict)
                    else getattr(item, "type", None)
                )
                if item_type == "video":
                    output_video = item
                    break
            if output_video is not None:
                break

    if output_video is None:
        return None, None

    uri = (
        output_video.get("uri")
        if isinstance(output_video, dict)
        else getattr(output_video, "uri", None)
    )
    data = (
        output_video.get("data")
        if isinstance(output_video, dict)
        else getattr(output_video, "data", None)
    )
    raw_bytes: bytes | None = None
    if data:
        raw_bytes = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    return uri, raw_bytes


class GeminiVideoGenerator:
    """Renders video clips from compiled `Package` objects via Vertex AI Gemini Omni / Veo strictly without silent fallbacks."""

    def __init__(
        self,
        caps: VideoProviderCfg | None = None,
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        self.caps = caps or VideoProviderCfg()
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("VEO_REGION", "global")

    def _download_gs_uri(self, gs_uri: str) -> bytes | None:
        if not gs_uri.startswith("gs://"):
            return None
        without = gs_uri[len("gs://") :]
        bucket_name, _, blob_path = without.partition("/")
        if not bucket_name or not blob_path:
            return None
        client = storage.Client(project=self.project)
        blob = client.bucket(bucket_name).blob(blob_path)
        return blob.download_as_bytes()

    def generate(self, package: Package) -> bytes:
        model_id = self.caps.model or "gemini-omni-1.1-flash-preview"
        is_omni = "omni" in model_id.lower()
        aspect = (
            package.aspect_ratio if package.aspect_ratio in ("16:9", "9:16") else "16:9"
        )

        try:
            if is_omni:
                client = genai.Client(
                    vertexai=True, project=self.project, location="global"
                )
                duration = max(3, min(10, int(round(package.duration_s or 5))))
                response_format_block: dict[str, Any] = {
                    "type": "video",
                    "aspect_ratio": aspect,
                    "resolution": "720p",
                    "duration": f"{duration}s",
                }
                bucket = os.getenv("GCS_BUCKET")
                if bucket:
                    response_format_block["delivery"] = "uri"
                    response_format_block["gcs_uri"] = (
                        f"gs://{bucket}/storygraph_renders/{package.shot_id}/"
                    )

                input_blocks: list[dict[str, Any]] = [
                    {"type": "text", "text": package.compiled_prompt}
                ]
                image_uris: list[str] = []
                if package.first_frame_uri and package.first_frame_uri.startswith(
                    "gs://"
                ):
                    image_uris.append(package.first_frame_uri)
                for r_uri in package.reference_uris:
                    if r_uri and r_uri.startswith("gs://") and r_uri not in image_uris:
                        image_uris.append(r_uri)
                for img_uri in image_uris[: self.caps.max_reference_images or 3]:
                    input_blocks.append(
                        {"type": "image", "uri": img_uri, "mime_type": "image/png"}
                    )
                video_task = (
                    "image_to_video" if len(input_blocks) > 1 else "text_to_video"
                )

                try:
                    interaction = client.interactions.create(
                        model=model_id,
                        background=False,
                        input=input_blocks,
                        response_format=[response_format_block],
                        generation_config={"video_config": {"task": video_task}},
                    )
                except Exception:
                    if len(input_blocks) > 2:
                        try:
                            interaction = client.interactions.create(
                                model=model_id,
                                background=False,
                                input=input_blocks[:2],
                                response_format=[response_format_block],
                                generation_config={
                                    "video_config": {"task": "image_to_video"}
                                },
                            )
                        except Exception:
                            interaction = client.interactions.create(
                                model=model_id,
                                background=False,
                                input=input_blocks[:1],
                                response_format=[response_format_block],
                                generation_config={
                                    "video_config": {"task": "text_to_video"}
                                },
                            )
                    elif len(input_blocks) == 2:
                        interaction = client.interactions.create(
                            model=model_id,
                            background=False,
                            input=input_blocks[:1],
                            response_format=[response_format_block],
                            generation_config={
                                "video_config": {"task": "text_to_video"}
                            },
                        )
                    else:
                        raise

                interaction_id = getattr(interaction, "id", None) or (
                    interaction.get("id") if isinstance(interaction, dict) else ""
                )
                deadline = time.time() + 180
                while (
                    getattr(interaction, "status", None) in ("in_progress", "queued")
                    and time.time() < deadline
                ):
                    time.sleep(6)
                    interaction = client.interactions.get(interaction_id)

                uri, raw_bytes = _extract_omni_video_payload(interaction)
                if raw_bytes and len(raw_bytes) > 256:
                    return raw_bytes
                if uri:
                    dl_bytes = self._download_gs_uri(uri)
                    if dl_bytes and len(dl_bytes) > 256:
                        return dl_bytes
            else:
                client = genai.Client(
                    vertexai=True, project=self.project, location=self.location
                )
                op = client.models.generate_videos(
                    model=model_id,
                    prompt=package.compiled_prompt,
                    config=types.GenerateVideosConfig(
                        aspect_ratio=aspect,
                        duration_seconds=int(round(package.duration_s)),
                        negative_prompt=package.negative_prompt or None,
                        seed=package.seed,
                    ),
                )
                deadline = time.time() + 240
                while not op.done and time.time() < deadline:
                    time.sleep(5)
                    op = client.operations.get(op)
                if op.done and op.result and op.result.generated_videos:
                    vid = op.result.generated_videos[0].video
                    if vid and vid.video_bytes:
                        return bytes(vid.video_bytes)
                    if vid and getattr(vid, "uri", None):
                        dl_bytes = self._download_gs_uri(str(vid.uri))
                        if dl_bytes and len(dl_bytes) > 256:
                            return dl_bytes
        except Exception as exc:
            raise StoryGraphError(
                f"GeminiVideoGenerator ({model_id}) failed for shot '{package.shot_id}': {exc}"
            ) from exc
        raise StoryGraphError(
            f"GeminiVideoGenerator ({model_id}) returned no video bytes for shot '{package.shot_id}'"
        )

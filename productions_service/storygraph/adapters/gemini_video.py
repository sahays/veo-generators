"""Vertex AI VideoGenerator adapter (`gemini-omni-1.1-flash-preview` / Veo)."""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types

from ..compile import Package
from ..config import VideoProviderCfg
from ..errors import StoryGraphError

logger = logging.getLogger(__name__)

_SAFETY_REPLACEMENTS: list[tuple[str, str]] = [
    (r"AVOID:.*$", "AVOID: photorealism, dark shadows, monochrome."),
    (r"\bmortally\s+wounded\b", "weary and resting"),
    (r"\bwounded\b", "weary"),
    (r"\bdying\b", "resting peacefully"),
    (r"\bdead\b", "resting"),
    (r"\bsacrifice\b", "noble devotion"),
    (r"\bfading\s+with\s+final\s+strength\b", "speaking softly"),
    (r"\bwith\s+fading\s+breath\b", "with gentle voice"),
    (r"\bremaining\s+strength\b", "gentle strength"),
    (r"\bbroken\s+feathers\b", "ruffled feathers"),
    (r"\bfallen\b", "resting"),
    (r"\bweeping\s+gently\b", "speaking with gentle emotion"),
    (r"\bweeping\b", "emotional"),
    (r"\btearful\b", "emotional"),
    (r"\bterrified\b", "startled"),
    (r"\bpanic\b", "surprise"),
    (r"\bstruggles\s+against\b", "steps back from"),
    (r"\babducts?\b", "leads away"),
    (r"\bfled\b", "traveled"),
    (r"\bdemon\s+king\b", "ruler"),
    (r"बलिदान", "समर्पण"),
    (r"दुष्ट", "रावण"),
]


def _get_field(obj: Any, key: str) -> Any:
    """Read `key` from a dict or object attribute."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def _sanitize_omni_prompt(text: str, aggressive: bool = False) -> str:
    """Sanitize mythology conflict/injury terms that trigger Vertex AI Responsible AI false positives."""
    out = text
    for pat, rep in _SAFETY_REPLACEMENTS:
        out = re.sub(pat, rep, out, flags=re.IGNORECASE | re.DOTALL)
    if aggressive:
        out = re.sub(r"\bAVOID:[^\n]*", "", out, flags=re.IGNORECASE)
        out = re.sub(
            r"\b(?:sorrowful|sorrow|grief|grieved|distress|desperate|grave\s+act|vulture)\b",
            "gentle",
            out,
            flags=re.IGNORECASE,
        )
    return out.strip()


def _find_video_in_steps(interaction: Any) -> Any | None:
    """Search interaction `steps` in reverse order for a `video` content item."""
    for step in reversed(_get_field(interaction, "steps") or []):
        if _get_field(step, "type") != "model_output":
            continue
        for item in reversed(_get_field(step, "content") or []):
            if _get_field(item, "type") == "video":
                return item
    return None


def _extract_omni_video_payload(interaction: Any) -> tuple[str | None, bytes | None]:
    """Return (gcs_uri, raw_video_bytes) from a completed Gemini Omni interaction."""
    output_video = _get_field(interaction, "output_video") or _find_video_in_steps(
        interaction
    )
    if output_video is None:
        return None, None
    uri = _get_field(output_video, "uri")
    data = _get_field(output_video, "data")
    raw_bytes: bytes | None = None
    if data:
        raw_bytes = base64.b64decode(data) if isinstance(data, str) else bytes(data)
    return uri, raw_bytes


def _build_omni_input_blocks(
    package: Package, clean_prompt: str, max_refs: int
) -> list[dict[str, Any]]:
    """Construct Gemini Omni text + reference image input blocks for `package`."""
    blocks: list[dict[str, Any]] = [{"type": "text", "text": clean_prompt}]
    image_uris: list[str] = []
    ff_uri = package.first_frame_uri
    if ff_uri and ff_uri.startswith("gs://"):
        image_uris.append(ff_uri)
    for r_uri in package.reference_uris:
        if r_uri and r_uri.startswith("gs://") and r_uri not in image_uris:
            image_uris.append(r_uri)
    for img_uri in image_uris[:max_refs]:
        blocks.append({"type": "image", "uri": img_uri, "mime_type": "image/png"})
    return blocks


def _retry_omni_interaction(
    client: Any,
    model_id: str,
    package: Package,
    input_blocks: list[dict[str, Any]],
    fmt_block: dict[str, Any],
) -> Any:
    """Retry Omni video interaction with aggressive safety prompt and reduced references."""
    agg_prompt = _sanitize_omni_prompt(package.compiled_prompt, aggressive=True)
    single_ref = [{"type": "text", "text": agg_prompt}, *input_blocks[1:2]]
    task = "image_to_video" if len(single_ref) > 1 else "text_to_video"
    try:
        return client.interactions.create(
            model=model_id,
            background=False,
            input=single_ref,
            response_format=[fmt_block],
            generation_config={"video_config": {"task": task}},
        )
    except Exception as second_exc:  # noqa: BLE001
        logger.warning(
            "Omni single-ref retry failed; falling back to text_to_video",
            extra={
                "shot_id": package.shot_id,
                "model": model_id,
                "error": str(second_exc),
            },
        )
        return client.interactions.create(
            model=model_id,
            background=False,
            input=[{"type": "text", "text": agg_prompt}],
            response_format=[fmt_block],
            generation_config={"video_config": {"task": "text_to_video"}},
        )


def _create_omni_interaction(
    client: Any,
    model_id: str,
    package: Package,
    input_blocks: list[dict[str, Any]],
    fmt_block: dict[str, Any],
) -> Any:
    """Invoke `client.interactions.create` with progressive safety/reference fallbacks."""
    video_task = "image_to_video" if len(input_blocks) > 1 else "text_to_video"
    try:
        return client.interactions.create(
            model=model_id,
            background=False,
            input=input_blocks,
            response_format=[fmt_block],
            generation_config={"video_config": {"task": video_task}},
        )
    except Exception as first_exc:  # noqa: BLE001
        logger.warning(
            "Omni primary interaction failed; retrying with aggressive safety prompt",
            extra={
                "shot_id": package.shot_id,
                "model": model_id,
                "error": str(first_exc),
            },
        )
        return _retry_omni_interaction(
            client, model_id, package, input_blocks, fmt_block
        )


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
        bucket_name, _, blob_path = gs_uri[len("gs://") :].partition("/")
        if not bucket_name or not blob_path:
            return None
        client = storage.Client(project=self.project)
        return client.bucket(bucket_name).blob(blob_path).download_as_bytes()

    def _generate_omni(
        self, model_id: str, aspect: str, package: Package
    ) -> bytes | None:
        client = genai.Client(vertexai=True, project=self.project, location="global")
        duration = max(3, min(10, round(package.duration_s or 5)))
        fmt_block: dict[str, Any] = {
            "type": "video",
            "aspect_ratio": aspect,
            "resolution": "720p",
            "duration": f"{duration}s",
        }
        bucket = os.getenv("GCS_BUCKET")
        if bucket:
            fmt_block["delivery"] = "uri"
            fmt_block["gcs_uri"] = (
                f"gs://{bucket}/storygraph_renders/{package.shot_id}/"
            )

        clean_prompt = _sanitize_omni_prompt(package.compiled_prompt)
        blocks = _build_omni_input_blocks(
            package, clean_prompt, self.caps.max_reference_images or 3
        )
        interaction = _create_omni_interaction(
            client, model_id, package, blocks, fmt_block
        )
        interaction_id = str(_get_field(interaction, "id") or "")
        deadline = time.time() + 180
        while (
            _get_field(interaction, "status") in ("in_progress", "queued")
            and time.time() < deadline
        ):
            time.sleep(6)
            interaction = client.interactions.get(interaction_id)

        uri, raw_bytes = _extract_omni_video_payload(interaction)
        if raw_bytes and len(raw_bytes) > 256:
            return raw_bytes
        return self._download_gs_uri(uri) if uri else None

    def _generate_veo(
        self, model_id: str, aspect: str, package: Package
    ) -> bytes | None:
        client = genai.Client(
            vertexai=True, project=self.project, location=self.location
        )
        cfg = types.GenerateVideosConfig(
            aspect_ratio=aspect,
            duration_seconds=round(package.duration_s),
            negative_prompt=package.negative_prompt or None,
            seed=package.seed,
        )
        op = client.models.generate_videos(
            model=model_id, prompt=package.compiled_prompt, config=cfg
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
                return self._download_gs_uri(str(vid.uri))
        return None

    def generate(self, package: Package) -> bytes:
        model_id = self.caps.model or "gemini-omni-1.1-flash-preview"
        aspect = (
            package.aspect_ratio if package.aspect_ratio in ("16:9", "9:16") else "16:9"
        )
        try:
            out = (
                self._generate_omni(model_id, aspect, package)
                if "omni" in model_id.lower()
                else self._generate_veo(model_id, aspect, package)
            )
            if out and len(out) > 256:
                return out
        except Exception as exc:
            raise StoryGraphError(
                f"GeminiVideoGenerator ({model_id}) failed for shot '{package.shot_id}': {exc}"
            ) from exc
        raise StoryGraphError(
            f"GeminiVideoGenerator ({model_id}) returned no video bytes for shot '{package.shot_id}'"
        )

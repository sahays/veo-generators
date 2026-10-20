"""Vertex AI VideoGenerator adapter (`gemini-omni-1.1-flash-preview` / Veo)."""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any

from google import genai
from google.cloud import storage
from google.genai import types

from ..compile import Package
from ..config import VideoProviderCfg
from ..errors import StoryGraphError
from .omni.fallback import (
    FallbackRecord,
    LadderStep,
    build_ladder,
    log_downgrade,
    make_record,
)
from .omni.inputs import OmniRequest, build_omni_request
from .omni.package import RenderPackage
from .omni.safety import SafetyProfile, select_safety_profile

logger = logging.getLogger(__name__)


def _get_field(obj: Any, key: str) -> Any:
    """Read `key` from a dict or object attribute."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


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
    """Interleaved (label, image) Omni input blocks for `package` (first frame tag-bound)."""
    return build_omni_request(package, clean_prompt, max_refs).blocks


def _profile_for(package: Package) -> SafetyProfile:
    if isinstance(package, RenderPackage):
        return select_safety_profile(package.visual_style_preset, package.language)
    return select_safety_profile("", "")


def _send(
    client: Any, model_id: str, request: OmniRequest, fmt_block: dict[str, Any]
) -> Any:
    gen_cfg: dict[str, Any] = (
        {"video_config": {"task": request.task}} if request.task else {}
    )
    return client.interactions.create(
        model=model_id,
        background=False,
        input=request.blocks,
        response_format=[fmt_block],
        generation_config=gen_cfg,
    )


def _create_omni_interaction(
    client: Any,
    model_id: str,
    package: Package,
    ladder: list[LadderStep],
    fmt_block: dict[str, Any],
) -> tuple[Any, int, list[str]]:
    """Walk the fallback ladder; return (interaction, rung index used, errors seen)."""
    errors: list[str] = []
    profile = _profile_for(package)
    for idx, step in enumerate(ladder):
        try:
            return _send(client, model_id, step.request, fmt_block), idx, errors
        except Exception as exc:  # provider raises untyped errors
            errors.append(f"{step.level}: {exc}")
            if idx + 1 >= len(ladder):
                raise
            log_downgrade(package, model_id, profile, ladder, idx + 1, str(exc))
    raise StoryGraphError(f"Omni ladder empty for shot '{package.shot_id}'")


class GeminiVideoGenerator:
    """Renders clips from compiled `Package`s via Vertex AI Gemini Omni / Veo.

    Omni requests that the provider rejects are retried down an explicit ladder
    (aggressive safety rewrite + single identity ref, then text-only). Every downgrade
    is logged semantically and exposed via `pop_fallback(shot_id)` so the pipeline can
    persist it on the GenerationRun; there are no unlogged fallbacks.
    """

    def __init__(
        self,
        caps: VideoProviderCfg | None = None,
        project: str | None = None,
        location: str | None = None,
    ) -> None:
        self.caps = caps or VideoProviderCfg()
        self.project = project or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or os.getenv("VEO_REGION", "global")
        self._fallbacks: dict[str, FallbackRecord] = {}
        self._lock = threading.Lock()

    def pop_fallback(self, shot_id: str) -> FallbackRecord | None:
        """Return and clear the fallback record of the latest render of `shot_id`."""
        with self._lock:
            return self._fallbacks.pop(shot_id, None)

    def _record_fallback(self, record: FallbackRecord | None, shot_id: str) -> None:
        with self._lock:
            if record is None:
                self._fallbacks.pop(shot_id, None)
            else:
                self._fallbacks[shot_id] = record

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
        resolution = (
            package.resolution
            if package.resolution in ("360p", "720p", "1080p")
            else "360p"
        )
        fmt_block: dict[str, Any] = {
            "type": "video",
            "aspect_ratio": aspect,
            "resolution": resolution,
            "duration": f"{duration}s",
        }
        bucket = os.getenv("GCS_BUCKET")
        if bucket:
            fmt_block["delivery"] = "uri"
            fmt_block["gcs_uri"] = (
                f"gs://{bucket}/storygraph_renders/{package.shot_id}/"
            )

        interaction = self._run_ladder(client, model_id, package, fmt_block)
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

    def _run_ladder(
        self, client: Any, model_id: str, package: Package, fmt_block: dict[str, Any]
    ) -> Any:
        self._record_fallback(None, package.shot_id)
        profile = _profile_for(package)
        ladder = build_ladder(
            package,
            profile,
            self.caps.max_reference_images or 3,
            self.caps.first_frame_mode,
        )
        interaction, used, errors = _create_omni_interaction(
            client, model_id, package, ladder, fmt_block
        )
        record = (
            make_record(package, model_id, profile, ladder, used, errors)
            if used
            else None
        )
        self._record_fallback(record, package.shot_id)
        return interaction

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

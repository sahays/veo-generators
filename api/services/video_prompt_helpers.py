"""Prompt building and Omni interaction extraction helpers for VideoService."""

from __future__ import annotations

import base64
import os
from typing import Any, Optional

from ai_helpers import resolve_model
from models import Project, Scene
from prompt_templates import PHYSICAL_REALISM_DIRECTIVE


def _log_ctx(where: str, what: str, why: str = "video_generation") -> dict[str, str]:
    return {
        "who": "video_service",
        "where": where,
        "what": what,
        "why": why,
        "how": "veo_omni",
    }


def _is_omni_model(model_id: str) -> bool:
    return model_id.startswith("gemini-omni")


def _resolve_model_and_resolution(
    firestore_svc: Any,
    project: Optional[Project],
    model_id: Optional[str],
    resolution: Optional[str],
    render_quality: Optional[str],
) -> tuple[str, str]:
    effective_quality = (
        render_quality
        or (getattr(project, "render_quality", None) if project else None)
        or "final"
    )
    effective_resolution = (
        resolution
        or (
            "360p"
            if effective_quality == "draft"
            else (getattr(project, "video_resolution", None) if project else None)
        )
        or "720p"
    )
    if effective_quality == "draft" or effective_resolution == "360p":
        effective_resolution = "360p"
        resolved_model = model_id or "gemini-omni-1.1-flash-preview"
        if not _is_omni_model(resolved_model):
            resolved_model = "gemini-omni-1.1-flash-preview"
        return resolved_model, effective_resolution
    if effective_resolution == "360p":
        effective_resolution = "720p"
    resolved_model = resolve_model(
        firestore_svc,
        "video",
        "VIDEO_GEN_MODEL",
        "gemini-omni-1.1-flash-preview",
        model_id,
    )
    return resolved_model, effective_resolution


def _resolve_ref_urls(
    scene: Scene, project: Optional[Project]
) -> tuple[Optional[str], Optional[str]]:
    ref_url = None
    if scene.thumbnail_url and scene.thumbnail_url.startswith("gs://"):
        ref_url = scene.thumbnail_url
    elif project and project.reference_image_url:
        ref_url = project.reference_image_url
    end_ref_url = None
    if getattr(scene, "end_frame_url", None) and scene.end_frame_url.startswith(
        "gs://"
    ):
        end_ref_url = scene.end_frame_url
    return ref_url, end_ref_url


def _build_omni_inputs(
    enriched_prompt: str,
    ref_url: Optional[str],
    end_ref_url: Optional[str],
    project: Optional[Project],
    effective_resolution: str,
    duration: int,
    project_id: str,
) -> tuple[list[dict], str, dict]:
    input_blocks: list[dict] = [{"type": "text", "text": enriched_prompt}]
    video_task = "text_to_video"
    for uri in (ref_url, end_ref_url):
        if uri and uri.startswith("gs://"):
            input_blocks.append({"type": "image", "uri": uri, "mime_type": "image/png"})
            video_task = "image_to_video"
    response_format_block: dict = {
        "type": "video",
        "aspect_ratio": project.orientation
        if project and project.orientation
        else "16:9",
        "resolution": effective_resolution,
        "duration": f"{duration}s",
    }
    bucket = os.getenv("GCS_BUCKET")
    if bucket:
        response_format_block["delivery"] = "uri"
        response_format_block["gcs_uri"] = f"gs://{bucket}/videos/{project_id}/"
    return input_blocks, video_task, response_format_block


def _append_camera_and_style(
    parts: list[str], scene: Scene, project: Optional[Project]
) -> None:
    orientation = project.orientation if project else None
    if orientation == "9:16":
        parts.append("Aspect ratio: 9:16 (portrait/vertical).")
    elif orientation == "16:9":
        parts.append("Aspect ratio: 16:9 (landscape/horizontal).")
    elif orientation:
        parts.append(f"Aspect ratio: {orientation}.")
    if scene.metadata:
        md = scene.metadata
        if md.camera_angle:
            parts.append(f"Camera angle: {md.camera_angle}.")
        if md.camera_movement:
            parts.append(f"Camera movement: {md.camera_movement}.")
        if md.cinematic_style:
            parts.append(f"Cinematic style: {md.cinematic_style}.")
        pace = md.pace or (
            project.global_style.pace if project and project.global_style else None
        )
        if pace:
            parts.append(f"Pace: {pace}.")
    elif project and project.global_style and project.global_style.pace:
        parts.append(f"Pace: {project.global_style.pace}.")


def _append_project_continuity(parts: list[str], project: Optional[Project]) -> None:
    if not project:
        return
    if project.global_style:
        gs = project.global_style
        parts.append(
            f"Style: {gs.look}. Mood: {gs.mood}. "
            f"Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
        )
    if project.continuity and project.continuity.characters:
        char_descs = [
            f"{c.id}: {c.description}, wearing {c.wardrobe}"
            for c in project.continuity.characters
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if project.continuity and project.continuity.setting_notes:
        parts.append(f"Setting: {project.continuity.setting_notes}.")


def _append_audio_directives(
    parts: list[str], scene: Scene, project: Optional[Project]
) -> None:
    if scene.music_transition:
        parts.append(f"Music transition: {scene.music_transition}")
    if scene.narration_enabled and scene.narration:
        lang = getattr(project, "language", None) or "en-IN"
        speaker_rule = (
            f" ({scene.speaker_notes})"
            if scene.speaker_notes
            else " (non-speaking on-screen characters must keep their mouths closed and not lip-sync someone else's lines)"
        )
        if lang == "hi-IN":
            parts.append(
                f'Voice-over narration in Hindi (hi-IN, native Hindi pronunciation){speaker_rule}: "{scene.narration}"'
            )
        elif lang == "en-IN":
            parts.append(
                f'Voice-over narration in English (India, en-IN, natural Indian English accent){speaker_rule}: "{scene.narration}"'
            )
        else:
            parts.append(f'Voice-over narration{speaker_rule}: "{scene.narration}"')
    if scene.music_enabled:
        music = scene.music_description or (
            project.global_style.soundtrack_style
            if project
            and project.global_style
            and project.global_style.soundtrack_style
            else None
        )
        if music:
            parts.append(f"Background music: {music}.")


def build_scene_video_prompt(
    scene: Scene, project: Optional[Project], duration: int
) -> str:
    """Build a video-specific prompt with duration, style, continuity, and audio."""
    parts = [f"{duration}-second video clip."]
    _append_camera_and_style(parts, scene, project)
    _append_project_continuity(parts, project)
    parts.append(scene.visual_description)
    if scene.speaker_notes:
        parts.append(f"Speaker & lip-sync rule: {scene.speaker_notes}.")
    if scene.eval_feedback:
        parts.append(f"STRICT CORRECTION FROM VIDEO EVAL: {scene.eval_feedback}.")
    parts.append(PHYSICAL_REALISM_DIRECTIVE)
    _append_audio_directives(parts, scene, project)
    return " ".join(parts)


def _find_video_item_in_steps(steps: Any) -> Any:
    for step in reversed(steps or []):
        step_type = (
            step.get("type") if isinstance(step, dict) else getattr(step, "type", None)
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
                return item
    return None


def extract_omni_video_uri(
    interaction: Any, name_hint: str, storage_svc: Any
) -> Optional[str]:
    """Extract a gs:// URI from a completed Gemini Omni interaction."""
    output_video = getattr(interaction, "output_video", None)
    if output_video is None and isinstance(interaction, dict):
        output_video = interaction.get("output_video")
    if output_video is None:
        steps = getattr(interaction, "steps", None)
        if steps is None and isinstance(interaction, dict):
            steps = interaction.get("steps")
        output_video = _find_video_item_in_steps(steps)
    if output_video is None:
        return None
    uri = (
        output_video.get("uri")
        if isinstance(output_video, dict)
        else getattr(output_video, "uri", None)
    )
    if uri:
        return uri
    data = (
        output_video.get("data")
        if isinstance(output_video, dict)
        else getattr(output_video, "data", None)
    )
    if data and storage_svc:
        video_bytes = base64.b64decode(data) if isinstance(data, str) else bytes(data)
        safe_name = name_hint.replace("/", "_").replace(":", "_")
        return storage_svc.upload_bytes(
            video_bytes, f"videos/{safe_name}.mp4", content_type="video/mp4"
        )
    return None

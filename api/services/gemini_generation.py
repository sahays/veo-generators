"""Image generation, collage, and prompt building helpers for GeminiService."""

from __future__ import annotations

from typing import Any, Optional

from google.genai import types

from adapt_prompts import ADAPT_PROMPT_TEMPLATE, adapt_prompt_variables
from ai_helpers import (
    compute_image_usage,
    extract_image_from_response,
    resolve_model,
    resolve_resource,
)
from helpers import gemini_call_with_retry
from models import AIResponseWrapper, Project, Scene
from prompt_resolver import gcs_ref_url
from prompt_templates import build_collage_prompt


def _append_project_style_and_continuity(
    parts: list[str], project: Optional[Project]
) -> None:
    if not project:
        return
    if project.global_style:
        gs = project.global_style
        parts.append(
            f"Style: {gs.look}. Mood: {gs.mood}. "
            f"Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
        )
    if project.continuity and project.continuity.characters:
        chars = [
            f"{c.id}: {c.description}, wearing {c.wardrobe}"
            for c in project.continuity.characters
        ]
        parts.append(f"Characters: {'; '.join(chars)}.")
    if project.continuity and project.continuity.setting_notes:
        parts.append(f"Setting: {project.continuity.setting_notes}.")


def _build_scene_prompt(
    scene: Scene,
    project: Optional[Project],
    orientation: Optional[str],
    frame_position: str = "start",
) -> str:
    """Build a flat scene keyframe prompt (start or end frame) from project context."""
    parts: list[str] = []
    if orientation:
        parts.append(f"Aspect ratio: {orientation}.")
    if frame_position == "end":
        parts.append(
            "KEYFRAME ROLE: END FRAME (final closing composition at the end of this scene's action). "
            "Depict the completed state of the action described below while keeping character identity, "
            "single-tail anatomy, wardrobe, held props, and background environment 100% consistent with the opening frame."
        )
    else:
        parts.append(
            "KEYFRAME ROLE: START FRAME (initial opening composition at the beginning of this scene's action)."
        )
    _append_project_style_and_continuity(parts, project)
    parts.append(scene.visual_description)
    if frame_position == "end" and scene.exit_transition:
        parts.append(f"End-of-shot camera framing: {scene.exit_transition}.")
    elif frame_position == "start" and scene.enter_transition:
        parts.append(f"Opening camera framing: {scene.enter_transition}.")
    if scene.speaker_notes:
        parts.append(f"Speaker/Action note: {scene.speaker_notes}.")
    if scene.eval_feedback:
        parts.append(f"STRICT CORRECTION: {scene.eval_feedback}.")
    return " ".join(parts)


def _build_ref_contents(
    project: Any,
    prompt: str,
    style_guide: bool = False,
    start_frame_uri: Optional[str] = None,
) -> list:
    """Build contents list with optional project reference image and/or scene start frame."""
    contents: list = []
    ref = gcs_ref_url(project)
    if ref:
        contents.append(types.Part.from_uri(file_uri=ref, mime_type="image/png"))
    if start_frame_uri and start_frame_uri.startswith("gs://"):
        contents.append(
            types.Part.from_uri(file_uri=start_frame_uri, mime_type="image/png")
        )
    if not contents:
        return [prompt]
    prefix_parts = []
    if ref and style_guide:
        prefix_parts.append("Use the reference image as a style guide.")
    if start_frame_uri and start_frame_uri.startswith("gs://"):
        prefix_parts.append(
            "Use the attached START frame of this scene as strict visual continuity reference "
            "(identical character face, wardrobe, single tail, props, and background environment) "
            "and generate the END frame showing the final pose/composition at the conclusion of this scene's action."
        )
    prefix = (" ".join(prefix_parts) + " ") if prefix_parts else ""
    contents.append(f"{prefix}{prompt}")
    return contents


class GeminiGenerationMixin:
    """Mixin providing image, adapt, collage, and overlay generation for GeminiService."""

    firestore_svc: Any
    storage_svc: Any
    prompts: Any

    def _get_client(self, region: str | None = None) -> Any:
        raise NotImplementedError

    async def generate_frame(
        self,
        project_id: str,
        scene: Scene,
        orientation: str,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
        frame_position: str = "start",
        start_frame_uri: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "image",
            "STORYBOARD_MODEL",
            "gemini-nano-banana-2.1",
            model_id,
        )
        client = self._get_client(region)
        prompt = prompt_override or _build_scene_prompt(
            scene, project, orientation, frame_position=frame_position
        )
        contents = _build_ref_contents(
            project,
            prompt,
            style_guide=True,
            start_frame_uri=start_frame_uri if frame_position == "end" else None,
        )
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=orientation),
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        url = extract_image_from_response(
            response, self.storage_svc, f"generated/{project_id}"
        )
        return AIResponseWrapper(
            data={
                "image_url": url,
                "generated_prompt": prompt,
                "frame_position": frame_position,
            },
            usage=compute_image_usage(response, model_id),
        )

    async def generate_adapt(
        self,
        source_gcs_uri: str,
        source_mime_type: str,
        aspect_ratio: str,
        template_gcs_uri: str | None = None,
        prompt_id: str = "",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "image",
            "ADAPTS_MODEL",
            "gemini-nano-banana-2.1",
            model_id,
        )
        prompt_text = (
            resolve_resource(self.firestore_svc, prompt_id) if prompt_id else None
        )
        template = prompt_text or ADAPT_PROMPT_TEMPLATE
        prompt = template.format(
            **adapt_prompt_variables(aspect_ratio, template_gcs_uri)
        )
        contents: list = [
            types.Part.from_uri(file_uri=source_gcs_uri, mime_type=source_mime_type)
        ]
        if template_gcs_uri:
            contents.append(
                types.Part.from_uri(file_uri=template_gcs_uri, mime_type="image/png")
            )
        contents.append(prompt)
        client = self._get_client(region)
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        url = extract_image_from_response(response, self.storage_svc, "adapts")
        return AIResponseWrapper(
            data={"image_url": url, "prompt_text_used": prompt},
            usage=compute_image_usage(response, model_id),
        )

    async def generate_thumbnail_collage(
        self,
        screenshot_uris: list[str],
        prompt_id: str,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "image",
            "STORYBOARD_MODEL",
            "gemini-nano-banana-2.1",
            model_id,
        )
        client = self._get_client(region)
        prompt = self.prompts.require_prompt(prompt_id)
        contents: list = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
        return await self._generate_image(
            client, model_id, contents, "16:9", "thumbnails"
        )

    async def generate_promo_collage(
        self,
        screenshot_uris: list[str],
        segments: list[dict] | None = None,
        orientation: str = "16:9",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "image",
            "STORYBOARD_MODEL",
            "gemini-nano-banana-2.1",
            model_id,
        )
        client = self._get_client(region)
        prompt = build_collage_prompt(segments)
        contents: list = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
        return await self._generate_image(
            client, model_id, contents, orientation, "promos/thumbnails"
        )

    async def generate_text_overlay(
        self,
        text: str,
        orientation: str = "16:9",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "image",
            "STORYBOARD_MODEL",
            "gemini-nano-banana-2.1",
            model_id,
        )
        client = self._get_client(region)
        prompt = (
            "Create a lower-third text overlay graphic for a professional "
            f"video promo. The text reads: '{text.upper()}'. Style: bold "
            "white cinematic text with a subtle dark gradient at the bottom "
            "third. Top two-thirds should be completely black. Professional "
            "broadcast quality."
        )
        return await self._generate_image(
            client, model_id, [prompt], orientation, "promos/overlays"
        )

    async def _generate_image(
        self,
        client: Any,
        model_id: str,
        contents: list,
        aspect_ratio: str,
        dest_folder: str,
    ) -> AIResponseWrapper:
        """Contents → image generation → upload → response."""
        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        url = extract_image_from_response(response, self.storage_svc, dest_folder)
        return AIResponseWrapper(
            data={"image_url": url},
            usage=compute_image_usage(response, model_id),
        )

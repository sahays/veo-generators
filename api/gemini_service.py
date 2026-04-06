"""Gemini service — video analysis, image generation, and content creation."""

import logging
import os
from typing import Optional

from google import genai
from google.genai import types

from adapt_prompts import ADAPT_PROMPT_TEMPLATE, adapt_prompt_variables
from ai_helpers import (
    compute_usage,
    extract_image_from_response,
    image_generation_usage,
    load_schema,
    resolve_resource,
)
from brief_helpers import parse_scenes
from helpers import gemini_call_with_retry
from models import AIResponseWrapper, Project, Scene
from prompt_resolver import PromptResolver, gcs_ref_url
from prompt_templates import SCENE_ANALYSIS_PROMPT, build_collage_prompt

logger = logging.getLogger(__name__)


class GeminiService:
    def __init__(self, storage_svc=None, firestore_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GEMINI_REGION", "global")
        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc
        self.prompts = PromptResolver(firestore_svc)
        self.client = genai.Client(
            vertexai=True,
            project=self.project_id,
            location=self.location,
        )

    # ------------------------------------------------------------------
    # Brief analysis (production planning)
    # ------------------------------------------------------------------

    async def analyze_brief(
        self,
        project_id: str,
        concept: str,
        length: str,
        orientation: str,
        prompt_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        project_type: Optional[str] = None,
        project: Optional[Project] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self.prompts.resolve_brief_prompt(
            concept, length, orientation, prompt_id, project_type, project
        )
        schema = self.prompts.resolve_schema(
            schema_id, "project-analysis", "production-schema"
        )
        contents = _build_ref_contents(project, prompt)
        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        scenes, global_style, continuity = parse_scenes(response.parsed)
        return AIResponseWrapper(
            data={
                "scenes": scenes,
                "global_style": global_style,
                "continuity": continuity,
                "analysis_prompt": prompt,
            },
            usage=compute_usage(response, model_id),
        )

    # ------------------------------------------------------------------
    # Frame / image generation
    # ------------------------------------------------------------------

    async def generate_frame(
        self,
        project_id: str,
        scene: Scene,
        orientation: str,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = prompt_override or _build_scene_prompt(scene, project, orientation)
        contents = _build_ref_contents(project, prompt, style_guide=True)
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=orientation),
            ),
        )
        url = extract_image_from_response(
            response, self.storage_svc, f"generated/{project_id}"
        )
        return AIResponseWrapper(
            data={"image_url": url, "generated_prompt": prompt},
            usage=image_generation_usage(model_id),
        )

    # ------------------------------------------------------------------
    # Adapt (multi-aspect-ratio image generation)
    # ------------------------------------------------------------------

    async def generate_adapt(
        self,
        source_gcs_uri: str,
        source_mime_type: str,
        aspect_ratio: str,
        template_gcs_uri: str | None = None,
        prompt_id: str = "",
    ) -> AIResponseWrapper:
        model_id = os.getenv("ADAPTS_MODEL", "gemini-3.1-flash-image-preview")
        prompt_text = None
        if prompt_id:
            prompt_text = resolve_resource(self.firestore_svc, prompt_id)
        if not prompt_text:
            prompt_text = ADAPT_PROMPT_TEMPLATE
        variables = adapt_prompt_variables(aspect_ratio, template_gcs_uri)
        prompt = prompt_text.format(**variables)

        contents: list = [
            types.Part.from_uri(file_uri=source_gcs_uri, mime_type=source_mime_type),
        ]
        if template_gcs_uri:
            contents.append(
                types.Part.from_uri(file_uri=template_gcs_uri, mime_type="image/png")
            )
        contents.append(prompt)
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        url = extract_image_from_response(response, self.storage_svc, "adapts")
        return AIResponseWrapper(
            data={"image_url": url, "prompt_text_used": prompt},
            usage=image_generation_usage(model_id),
        )

    # ------------------------------------------------------------------
    # Video analysis
    # ------------------------------------------------------------------

    async def analyze_video_key_moments(
        self,
        gcs_uri: str,
        mime_type: str,
        prompt_id: str,
        schema_id: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self.prompts.require_prompt(prompt_id)
        schema = self.prompts.resolve_schema(
            schema_id, "key-moments", "key-moments-schema"
        )
        return await self._analyze_video(model_id, gcs_uri, mime_type, prompt, schema)

    async def analyze_video_for_thumbnails(
        self, gcs_uri: str, mime_type: str, prompt_id: str
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self.prompts.require_prompt(prompt_id)
        schema = load_schema("thumbnail-analysis-schema")
        return await self._analyze_video(model_id, gcs_uri, mime_type, prompt, schema)

    async def analyze_video_focal_points(
        self,
        gcs_uri: str,
        mime_type: str = "video/mp4",
        prompt_id: str = "",
        content_type: str = "other",
        chirp_context: str = "",
    ) -> AIResponseWrapper:
        from reframe_strategies import resolve_prompt

        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt_text, prompt_variables = None, {}
        if prompt_id and self.firestore_svc:
            content = resolve_resource(self.firestore_svc, prompt_id)
            if content:
                prompt_text = content
        if not prompt_text:
            prompt_text, prompt_variables = resolve_prompt(content_type)
        if chirp_context:
            prompt_text = chirp_context + "\n\n" + prompt_text

        schema = load_schema("reframe-focal-points-schema")
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=65536,
            ),
        )
        data = (
            response.parsed
            if isinstance(response.parsed, dict)
            else {"focal_points": [], "scene_changes": []}
        )
        data["prompt_variables"] = prompt_variables
        data["prompt_text_used"] = prompt_text
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

    async def analyze_video_scenes(
        self,
        gcs_uri: str,
        mime_type: str = "video/mp4",
        content_type: str = "other",
        chirp_context: str = "",
    ) -> AIResponseWrapper:
        """Scene-based reframing analysis (used with MediaPipe)."""
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt_text = SCENE_ANALYSIS_PROMPT
        prompt_variables = {"mode": "scene-based", "content_type": content_type}
        if chirp_context:
            prompt_text = chirp_context + "\n\n" + prompt_text

        schema = load_schema("reframe-scenes-schema")
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=65536,
            ),
        )
        data = response.parsed if isinstance(response.parsed, dict) else {"scenes": []}
        data["prompt_variables"] = prompt_variables
        data["prompt_text_used"] = prompt_text
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

    async def analyze_video_for_promo(
        self,
        gcs_uri: str,
        mime_type: str = "video/mp4",
        target_duration: int = 60,
        prompt_id: str = "",
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self.prompts.resolve_promo_prompt(prompt_id, target_duration)
        schema = load_schema("promo-segments-schema")
        return await self._analyze_video(model_id, gcs_uri, mime_type, prompt, schema)

    # ------------------------------------------------------------------
    # Collage / overlay generation
    # ------------------------------------------------------------------

    async def generate_thumbnail_collage(
        self, screenshot_uris: list[str], prompt_id: str
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = self.prompts.require_prompt(prompt_id)
        contents = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
        return await self._generate_image(model_id, contents, "16:9", "thumbnails")

    async def generate_promo_collage(
        self,
        screenshot_uris: list[str],
        segments: list[dict] | None = None,
        orientation: str = "16:9",
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = build_collage_prompt(segments)
        contents = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
        return await self._generate_image(
            model_id, contents, orientation, "promos/thumbnails"
        )

    async def generate_text_overlay(
        self, text: str, orientation: str = "16:9"
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = (
            "Create a lower-third text overlay graphic for a professional "
            f"video promo. The text reads: '{text.upper()}'. Style: bold "
            "white cinematic text with a subtle dark gradient at the bottom "
            "third. Top two-thirds should be completely black. Professional "
            "broadcast quality."
        )
        return await self._generate_image(
            model_id, [prompt], orientation, "promos/overlays"
        )

    # ------------------------------------------------------------------
    # Shared internal helpers
    # ------------------------------------------------------------------

    async def _analyze_video(
        self, model_id, gcs_uri, mime_type, prompt, schema
    ) -> AIResponseWrapper:
        """Video + prompt → structured JSON response."""
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt,
        ]
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=65536,
            ),
        )
        data = response.parsed if isinstance(response.parsed, dict) else {}
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

    async def _generate_image(
        self, model_id, contents, aspect_ratio, dest_folder
    ) -> AIResponseWrapper:
        """Contents → image generation → upload → response."""
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        url = extract_image_from_response(response, self.storage_svc, dest_folder)
        return AIResponseWrapper(
            data={"image_url": url},
            usage=image_generation_usage(model_id),
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _build_scene_prompt(
    scene: Scene, project: Optional[Project], orientation: Optional[str]
) -> str:
    """Build a flat scene prompt from project context."""
    parts = []
    if orientation:
        parts.append(f"Aspect ratio: {orientation}.")
    if project and project.global_style:
        gs = project.global_style
        parts.append(
            f"Style: {gs.look}. Mood: {gs.mood}. "
            f"Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
        )
    if project and project.continuity and project.continuity.characters:
        chars = [
            f"{c.id}: {c.description}, wearing {c.wardrobe}"
            for c in project.continuity.characters
        ]
        parts.append(f"Characters: {'; '.join(chars)}.")
    if project and project.continuity and project.continuity.setting_notes:
        parts.append(f"Setting: {project.continuity.setting_notes}.")
    parts.append(scene.visual_description)
    return " ".join(parts)


def _build_ref_contents(project, prompt, style_guide: bool = False) -> list:
    """Build contents list with optional reference image."""
    ref = gcs_ref_url(project)
    if not ref:
        return [prompt]
    prefix = "Use the above reference image as a style guide. " if style_guide else ""
    return [
        types.Part.from_uri(file_uri=ref, mime_type="image/png"),
        f"{prefix}{prompt}",
    ]

"""AI service — Gemini-powered video analysis and image generation."""

import logging
import os
from collections import defaultdict
from typing import Optional

from google import genai
from google.genai import types

from ai_helpers import (
    compute_usage,
    extract_image_from_response,
    image_generation_usage,
    load_schema,
    resolve_resource,
)
from helpers import gemini_call_with_retry
from models import Scene, SceneMetadata, AIResponseWrapper, Project

logger = logging.getLogger(__name__)

_CATEGORY_MAP = {
    "movie": "production-movie",
    "advertizement": "production-ad",
    "social": "production-social",
}


def _gcs_ref_url(project: Optional["Project"]) -> str | None:
    """Return GCS reference image URL if available, else None."""
    url = project.reference_image_url if project else None
    return url if url and url.startswith("gs://") else None


class AIService:
    def __init__(self, storage_svc=None, firestore_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GEMINI_REGION", "global")
        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc
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
        prompt = self._resolve_brief_prompt(
            concept,
            length,
            orientation,
            prompt_id,
            project_type,
            project,
        )
        schema = self._resolve_schema(
            schema_id, "project-analysis", "production-schema"
        )

        contents = self._build_brief_contents(project, prompt)
        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        scenes, global_style, continuity = _parse_scenes(response.parsed)
        usage = compute_usage(response, model_id)
        return AIResponseWrapper(
            data={
                "scenes": scenes,
                "global_style": global_style,
                "continuity": continuity,
                "analysis_prompt": prompt,
            },
            usage=usage,
        )

    def _resolve_brief_prompt(
        self, concept, length, orientation, prompt_id, project_type, project
    ) -> str:
        """Resolve and format the brief analysis prompt."""
        template = self._lookup_brief_template(prompt_id, project_type)
        ref_note = (
            "A reference image is attached above — use it as a visual style guide."
            if _gcs_ref_url(project)
            else ""
        )
        return template.format_map(
            defaultdict(
                str,
                length=length,
                orientation=orientation,
                concept=concept,
                ref_images=ref_note,
            )
        )

    def _lookup_brief_template(self, prompt_id, project_type) -> str:
        """Resolve template: explicit ID > category > default. No nesting."""
        if not self.firestore_svc:
            return _DEFAULT_BRIEF_PROMPT
        if prompt_id:
            return (
                resolve_resource(self.firestore_svc, prompt_id) or _DEFAULT_BRIEF_PROMPT
            )
        category = _CATEGORY_MAP.get(project_type, "production-ad")
        return (
            resolve_resource(self.firestore_svc, "", "prompt", category)
            or _DEFAULT_BRIEF_PROMPT
        )

    def _build_brief_contents(self, project, prompt) -> list:
        ref = _gcs_ref_url(project)
        if not ref:
            return [prompt]
        return [types.Part.from_uri(file_uri=ref, mime_type="image/png"), prompt]

    def _resolve_schema(self, schema_id, category, default_name) -> dict:
        """Resolve JSON schema from Firestore or load default."""
        import json

        if self.firestore_svc:
            content = resolve_resource(
                self.firestore_svc, schema_id or "", "schema", category
            )
            if content:
                return json.loads(content)
        return load_schema(default_name)

    # ------------------------------------------------------------------
    # Scene prompt building
    # ------------------------------------------------------------------

    def _build_scene_prompt(
        self,
        scene: Scene,
        project: Optional[Project],
        orientation: Optional[str] = None,
    ) -> str:
        parts = []
        if orientation:
            parts.append(f"Aspect ratio: {orientation}.")
        if project and project.global_style:
            gs = project.global_style
            parts.append(
                f"Style: {gs.look}. Mood: {gs.mood}. Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
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
        prompt = prompt_override or self._build_scene_prompt(
            scene, project, orientation
        )
        contents = self._build_image_contents(project, prompt)

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

    def _build_image_contents(self, project, prompt) -> list:
        ref = _gcs_ref_url(project)
        if not ref:
            return [prompt]
        return [
            types.Part.from_uri(file_uri=ref, mime_type="image/png"),
            f"Use the above reference image as a style guide. {prompt}",
        ]

    # ------------------------------------------------------------------
    # Video analysis methods
    # ------------------------------------------------------------------

    async def analyze_video_key_moments(
        self,
        gcs_uri: str,
        mime_type: str,
        prompt_id: str,
        schema_id: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self._require_prompt(prompt_id)
        schema = self._resolve_schema(schema_id, "key-moments", "key-moments-schema")
        return await self._analyze_video(model_id, gcs_uri, mime_type, prompt, schema)

    async def analyze_video_for_thumbnails(
        self, gcs_uri: str, mime_type: str, prompt_id: str
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt = self._require_prompt(prompt_id)
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
        """Analyze video for scene-based reframing (used with MediaPipe).

        Returns scenes with active_subject hints instead of x,y coordinates.
        """
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3.1-pro-preview")
        prompt_text = _SCENE_ANALYSIS_PROMPT
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
        prompt = self._resolve_promo_prompt(prompt_id, target_duration)
        schema = load_schema("promo-segments-schema")
        return await self._analyze_video(model_id, gcs_uri, mime_type, prompt, schema)

    # ------------------------------------------------------------------
    # Collage / overlay generation
    # ------------------------------------------------------------------

    async def generate_thumbnail_collage(
        self, screenshot_uris: list[str], prompt_id: str
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = self._require_prompt(prompt_id)
        contents = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio="16:9"),
            ),
        )
        url = extract_image_from_response(response, self.storage_svc, "thumbnails")
        return AIResponseWrapper(
            data={"thumbnail_url": url}, usage=image_generation_usage(model_id)
        )

    async def generate_promo_collage(
        self,
        screenshot_uris: list[str],
        segments: list[dict] | None = None,
        orientation: str = "16:9",
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = _build_collage_prompt(segments)
        contents = [
            types.Part.from_uri(file_uri=uri, mime_type="image/png")
            for uri in screenshot_uris
        ]
        contents.append(prompt)
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
            response, self.storage_svc, "promos/thumbnails"
        )
        return AIResponseWrapper(
            data={"image_url": url}, usage=image_generation_usage(model_id)
        )

    async def generate_text_overlay(
        self, text: str, orientation: str = "16:9"
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")
        prompt = (
            "Create a lower-third text overlay graphic for a professional video promo. "
            f"The text reads: '{text.upper()}'. "
            "Style: bold white cinematic text with a subtle dark gradient at the bottom third. "
            "Top two-thirds should be completely black. Professional broadcast quality."
        )
        response = await gemini_call_with_retry(
            self.client,
            model_id,
            [prompt],
            types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=orientation),
            ),
        )
        url = extract_image_from_response(response, self.storage_svc, "promos/overlays")
        return AIResponseWrapper(
            data={"image_url": url}, usage=image_generation_usage(model_id)
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _require_prompt(self, prompt_id: str) -> str:
        """Load a prompt from Firestore, raising if not found."""
        if not self.firestore_svc:
            raise ValueError("Firestore service not available")
        res = self.firestore_svc.get_resource(prompt_id)
        if not res:
            raise ValueError(f"Prompt resource not found: {prompt_id}")
        return res.content

    async def _analyze_video(
        self,
        model_id: str,
        gcs_uri: str,
        mime_type: str,
        prompt: str,
        schema: dict,
    ) -> AIResponseWrapper:
        """Common pattern: video + prompt → structured JSON response."""
        contents = [types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type), prompt]
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

    def _resolve_promo_prompt(self, prompt_id: str, target_duration: int) -> str:
        """Resolve promo prompt with variable substitution."""
        content = (
            resolve_resource(self.firestore_svc, prompt_id, "prompt", "promo")
            if self.firestore_svc
            else None
        )
        if content:
            return content.replace("{target_duration}", str(target_duration))
        return _default_promo_prompt(target_duration)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_scenes(data) -> tuple:
    """Parse Gemini response into Scene objects."""
    global_style = continuity = None
    if isinstance(data, dict):
        global_style = data.get("global_style")
        continuity = data.get("continuity")
        data = data.get("scenes", data)
    if not isinstance(data, list):
        return [], None, None

    scenes = []
    for s in data:
        metadata = s.get("metadata", {})
        if "character" in metadata and isinstance(metadata["character"], str):
            metadata["characters"] = [metadata.pop("character")]
        scenes.append(
            Scene(
                visual_description=s["visual_description"],
                timestamp_start=s["timestamp_start"],
                timestamp_end=s["timestamp_end"],
                metadata=SceneMetadata(**metadata),
                narration=s.get("narration"),
                narration_enabled=bool(s.get("narration")),
                music_description=s.get("music_description"),
                music_enabled=bool(s.get("music_description")),
                enter_transition=s.get("enter_transition"),
                exit_transition=s.get("exit_transition"),
                music_transition=s.get("music_transition"),
            )
        )
    return scenes, global_style, continuity


def _build_collage_prompt(segments: list[dict] | None) -> str:
    """Build prompt for promo collage with optional moment context."""
    base = (
        "Create a stylized collage thumbnail from these video screenshots. "
        "Arrange in a dynamic layout — NOT a simple grid. "
        "Include a close-up crop of a person's face. "
        "Cinematic styling: color grading, dramatic lighting, subtle vignette. "
        "Infer a short, punchy title and render as bold text. "
        "Style: professional broadcast quality, like ESPN or Netflix promos."
    )
    if not segments:
        return base
    lines = [
        f"- {s.get('title', '')}: {s.get('description', '')}"
        for s in segments
        if s.get("title")
    ]
    if lines:
        base += (
            "\n\nKey moments:\n"
            + "\n".join(lines)
            + "\n\nUse these to create a relevant title.\n"
        )
    return base


def _default_promo_prompt(target_duration: int) -> str:
    return (
        f"You are a professional video editor creating a {target_duration}-second "
        "promo/highlight reel. Select compelling moments. "
        f"Total duration ≈ {target_duration}s. Each segment 3-15s. "
        "Return segments in chronological order with title, description, "
        "timestamp_start, timestamp_end, relevance_score."
    )


_DEFAULT_BRIEF_PROMPT = """Act as a professional film director and scriptwriter.
Break the following creative brief into a scene-by-scene cinematic script.
Total length: {length} seconds.
Each scene must be between 2 and 8 seconds.

For each scene, provide:
- A detailed visual description for video generation
- Voice-over narration text spoken during the scene
- A music description for background music (genre, tempo, instruments, mood)

For each scene, also provide:
- An enter_transition: how the visuals begin, connecting from the previous scene (omit for the first scene)
- An exit_transition: how the visuals end, leading into the next scene (omit for the last scene)
- A music_transition: how background music should flow from the previous scene — prefer continuing the same track with gradual shifts in intensity/tempo rather than abrupt changes. Use crossfades, dynamic builds, or drops to silence only for dramatic effect. Omit for the first scene.

Also define a global soundtrack_style for the production's overall musical direction.

Creative Brief: {concept}

Return a JSON list of scenes following the requested structure."""

_SCENE_ANALYSIS_PROMPT = """You are analyzing this video for smart reframing from 16:9 to 9:16 (portrait).

Your job is to identify SCENES and WHO to focus on in each scene.

FACE TRACK DATA may be provided above — it tells you exactly which faces were detected and their typical horizontal positions (left/center/right). Use the track labels (Track A, Track B, etc.) in your active_subject field when available.

For each scene, provide:
- start_sec and end_sec (timestamps)
- description: what's happening
- active_subject: WHO to focus on. Use one of:
  * A track label: "Track A", "Track B" (preferred when tracks are provided)
  * A spatial hint: "left", "right", "center"
  * "largest" for the most prominent person
- scene_type: one of "dialogue", "action", "close-up", "establishing", "wide", "general"

RULES:
- Cover the entire video with no gaps between scenes
- Scene boundaries should be at camera cuts or significant subject changes
- For dialogue: alternate between the speaking person's track per scene
- For close-ups: use "center" (the face fills the frame)
- For wide/establishing shots: use "center"
- For action: use "largest" to track the most prominent moving subject
- Include t=0 to the final frame"""

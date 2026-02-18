import os
import json
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Optional
from google import genai
from google.genai import types
from models import Scene, SceneMetadata, UsageMetrics, AIResponseWrapper, Project


def _load_default_schema():
    schema_path = Path(__file__).parent / "schemas" / "production-schema.json"
    return json.loads(schema_path.read_text())


def _load_key_moments_schema():
    schema_path = Path(__file__).parent / "schemas" / "key-moments-schema.json"
    return json.loads(schema_path.read_text())


def _load_thumbnail_schema():
    schema_path = Path(__file__).parent / "schemas" / "thumbnail-analysis-schema.json"
    return json.loads(schema_path.read_text())


class AIService:
    def __init__(self, storage_svc=None, firestore_svc=None):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = os.getenv("GEMINI_REGION", "global")

        self.storage_svc = storage_svc
        self.firestore_svc = firestore_svc

        # Client for Text and Image
        self.client = genai.Client(
            vertexai=True, project=self.project_id, location=self.location
        )

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
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3-pro-preview")

        # 1. Resolve Prompt
        system_prompt_text = """Act as a professional film director and scriptwriter.
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

        if self.firestore_svc:
            fs = self.firestore_svc
            if prompt_id:
                res = fs.get_resource(prompt_id)
                if res:
                    system_prompt_text = res.content
            else:
                type_to_category = {
                    "movie": "production-movie",
                    "advertizement": "production-ad",
                    "social": "production-social",
                }
                category = type_to_category.get(project_type or "", "production-ad")
                res = fs.get_active_resource("prompt", category)
                if res:
                    system_prompt_text = res.content

        # Safe substitution: missing placeholders resolve to empty string
        ref_url = project.reference_image_url if project else None
        ref_images_note = (
            "A reference image is attached above — use it as a visual style guide."
            if ref_url and ref_url.startswith("gs://")
            else ""
        )
        prompt = system_prompt_text.format_map(
            defaultdict(
                str,
                length=length,
                orientation=orientation,
                concept=concept,
                ref_images=ref_images_note,
            )
        )

        # 2. Resolve Schema
        response_schema = _load_default_schema()

        if self.firestore_svc:
            fs = self.firestore_svc
            if schema_id:
                res = fs.get_resource(schema_id)
                if res:
                    response_schema = json.loads(res.content)
            else:
                res = fs.get_active_resource("schema", "project-analysis")
                if res:
                    response_schema = json.loads(res.content)

        # Build multimodal content: optional reference image + text prompt
        contents = []
        if ref_url and ref_url.startswith("gs://"):
            contents.append(
                types.Part.from_uri(file_uri=ref_url, mime_type="image/png")
            )
        contents.append(prompt)

        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=response_schema
            ),
        )

        scenes_data = response.parsed
        global_style = None
        continuity = None

        if isinstance(scenes_data, dict):
            global_style = scenes_data.get("global_style")
            continuity = scenes_data.get("continuity")
            scenes_data = scenes_data.get("scenes", scenes_data)

        if not isinstance(scenes_data, list):
            scenes_data = []

        scenes = []
        for s in scenes_data:
            metadata = s.get("metadata", {})
            # Handle legacy 'character' field by migrating to 'characters' list
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

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.000002)
            + (response.usage_metadata.candidates_token_count * 0.000012),
        )

        return AIResponseWrapper(
            data={
                "scenes": scenes,
                "global_style": global_style,
                "continuity": continuity,
                "analysis_prompt": prompt,
            },
            usage=usage,
        )

    def _build_scene_prompt(
        self,
        scene: Scene,
        project: Optional[Project],
        orientation: Optional[str] = None,
    ) -> str:
        """Build a rich prompt with production context for image generation."""
        parts = []
        if orientation == "9:16":
            parts.append("Aspect ratio: 9:16 (portrait/vertical).")
        elif orientation == "16:9":
            parts.append("Aspect ratio: 16:9 (landscape/horizontal).")
        elif orientation:
            parts.append(f"Aspect ratio: {orientation}.")
        if project and project.global_style:
            gs = project.global_style
            parts.append(
                f"Style: {gs.look}. Mood: {gs.mood}. "
                f"Colors: {gs.color_grading}. Lighting: {gs.lighting_style}."
            )
        if project and project.continuity and project.continuity.characters:
            char_descs = []
            for c in project.continuity.characters:
                char_descs.append(f"{c.id}: {c.description}, wearing {c.wardrobe}")
            parts.append(f"Characters: {'; '.join(char_descs)}.")
        if project and project.continuity and project.continuity.setting_notes:
            parts.append(f"Setting: {project.continuity.setting_notes}.")
        parts.append(scene.visual_description)
        return " ".join(parts)

    async def generate_frame(
        self,
        project_id: str,
        scene: Scene,
        orientation: str,
        project: Optional[Project] = None,
        prompt_override: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")

        enriched_prompt = prompt_override or self._build_scene_prompt(
            scene, project, orientation=orientation
        )

        # Build multimodal content: text prompt + optional reference image
        contents = []
        if project and project.reference_image_url:
            ref_url = project.reference_image_url
            if ref_url.startswith("gs://"):
                contents.append(
                    types.Part.from_uri(file_uri=ref_url, mime_type="image/png")
                )
            contents.append(
                f"Use the above reference image as a style guide. {enriched_prompt}"
            )
        else:
            contents.append(enriched_prompt)

        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio=orientation,
                ),
            ),
        )

        image_url = None

        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    if self.storage_svc:
                        dest = f"generated/{project_id}/{uuid.uuid4()}.png"
                        image_url = self.storage_svc.upload_bytes(
                            part.inline_data.data, dest
                        )
                    break

        if not image_url:
            raise ValueError("Frame generation produced no image")

        usage = UsageMetrics(model_name=model_id, cost_usd=0.134)
        return AIResponseWrapper(
            data={"image_url": image_url, "generated_prompt": enriched_prompt},
            usage=usage,
        )

    async def analyze_video_key_moments(
        self,
        gcs_uri: str,
        mime_type: str,
        prompt_id: str,
        schema_id: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3-pro-preview")

        # 1. Resolve Prompt (required)
        if not self.firestore_svc:
            raise ValueError("Firestore service not available")
        res = self.firestore_svc.get_resource(prompt_id)
        if not res:
            raise ValueError(f"Prompt resource not found: {prompt_id}")
        prompt_text = res.content

        # 2. Resolve Schema
        response_schema = _load_key_moments_schema()
        if schema_id:
            res = self.firestore_svc.get_resource(schema_id)
            if res:
                response_schema = json.loads(res.content)
        else:
            res = self.firestore_svc.get_active_resource("schema", "key-moments")
            if res:
                response_schema = json.loads(res.content)

        # 3. Build multimodal content
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]

        # 4. Call Gemini
        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        data = response.parsed
        if not isinstance(data, dict):
            data = {"key_moments": [], "video_summary": ""}

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.000002)
            + (response.usage_metadata.candidates_token_count * 0.000012),
        )

        return AIResponseWrapper(data=data, usage=usage)

    async def analyze_video_for_thumbnails(
        self,
        gcs_uri: str,
        mime_type: str,
        prompt_id: str,
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3-pro-preview")

        if not self.firestore_svc:
            raise ValueError("Firestore service not available")
        res = self.firestore_svc.get_resource(prompt_id)
        if not res:
            raise ValueError(f"Prompt resource not found: {prompt_id}")
        prompt_text = res.content

        response_schema = _load_thumbnail_schema()

        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]

        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            ),
        )

        data = response.parsed
        if not isinstance(data, dict):
            data = {"key_moments": [], "video_summary": ""}

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.000002)
            + (response.usage_metadata.candidates_token_count * 0.000012),
        )

        return AIResponseWrapper(data=data, usage=usage)

    async def generate_thumbnail_collage(
        self,
        screenshot_uris: list[str],
        prompt_id: str,
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")

        if not self.firestore_svc:
            raise ValueError("Firestore service not available")
        res = self.firestore_svc.get_resource(prompt_id)
        if not res:
            raise ValueError(f"Prompt resource not found: {prompt_id}")
        prompt_text = res.content

        contents = []
        for uri in screenshot_uris:
            contents.append(types.Part.from_uri(file_uri=uri, mime_type="image/png"))
        contents.append(prompt_text)

        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="16:9",
                ),
            ),
        )

        image_url = None
        if response.candidates and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    if self.storage_svc:
                        dest = f"thumbnails/{uuid.uuid4()}.png"
                        image_url = self.storage_svc.upload_bytes(
                            part.inline_data.data, dest
                        )
                    break

        if not image_url:
            raise ValueError("Collage generation produced no image")

        usage = UsageMetrics(model_name=model_id, cost_usd=0.134)
        return AIResponseWrapper(data={"thumbnail_url": image_url}, usage=usage)

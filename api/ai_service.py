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
    ) -> AIResponseWrapper:
        model_id = os.getenv("OPTIMIZE_PROMPT_MODEL", "gemini-3-pro-preview")

        # 1. Resolve Prompt
        system_prompt_text = """Act as a professional film director and scriptwriter.
Break the following creative brief into a scene-by-scene cinematic script.
Total length: {length} seconds.
Each scene must be between 2 and 8 seconds.

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
        prompt = system_prompt_text.format_map(
            defaultdict(str, length=length, orientation=orientation, concept=concept)
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

        response = self.client.models.generate_content(
            model=model_id,
            contents=prompt,
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
                )
            )

        usage = UsageMetrics(
            input_tokens=response.usage_metadata.prompt_token_count,
            output_tokens=response.usage_metadata.candidates_token_count,
            model_name=model_id,
            cost_usd=(response.usage_metadata.prompt_token_count * 0.00000125)
            + (response.usage_metadata.candidates_token_count * 0.00000375),
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

    def _build_scene_prompt(self, scene: Scene, project: Optional[Project]) -> str:
        """Build a rich prompt with production context for image generation."""
        parts = []
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
    ) -> AIResponseWrapper:
        model_id = os.getenv("STORYBOARD_MODEL", "gemini-3-pro-image-preview")

        enriched_prompt = self._build_scene_prompt(scene, project)

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

        usage = UsageMetrics(model_name=model_id, cost_usd=0.03)
        return AIResponseWrapper(
            data={"image_url": image_url, "generated_prompt": enriched_prompt},
            usage=usage,
        )

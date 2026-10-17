"""Gemini service — video analysis, image generation, and content creation."""

import json
import logging
import os
from typing import Any, Optional

from google import genai
from google.genai import types

from ai_helpers import compute_usage, load_schema, resolve_model
from brief_helpers import (
    parse_eval_response,
    parse_review_response,
    parse_scenes,
)
from gemini_generation import (
    GeminiGenerationMixin,
    _build_ref_contents,
    _build_scene_prompt,
)
from gemini_video_analysis import GeminiVideoAnalysisMixin
from helpers import gemini_call_with_retry
from models import AIResponseWrapper, Project
from prompt_resolver import PromptResolver
from prompt_templates import (
    FINISHED_VIDEO_EVAL_PROMPT,
    STORYBOARD_REVIEWER_PROMPT,
)

logger = logging.getLogger(__name__)

__all__ = ["GeminiService", "_build_ref_contents", "_build_scene_prompt"]


def _build_storyboard_payload(project: Project) -> dict:
    return {
        "project_name": project.name,
        "base_concept": project.base_concept,
        "orientation": project.orientation,
        "language": project.language,
        "global_style": project.global_style.dict() if project.global_style else {},
        "continuity": project.continuity.dict() if project.continuity else {},
        "scenes": [
            {
                "scene_number": idx + 1,
                "visual_description": s.visual_description,
                "timestamp_start": s.timestamp_start,
                "timestamp_end": s.timestamp_end,
                "narration": s.narration or "",
                "speaker_notes": s.speaker_notes or "",
                "music_description": s.music_description or "",
                "enter_transition": s.enter_transition or "",
                "exit_transition": s.exit_transition or "",
                "music_transition": s.music_transition or "",
                "metadata": s.metadata.dict() if s.metadata else {},
            }
            for idx, s in enumerate(project.scenes)
        ],
    }


def _build_eval_contents(project: Project, video_gcs_uri: Optional[str]) -> list:
    contents: list = []
    primary_uri = video_gcs_uri or project.final_video_url or project.draft_video_url
    if primary_uri and primary_uri.startswith("gs://"):
        contents.append(
            types.Part.from_uri(file_uri=primary_uri, mime_type="video/mp4")
        )
    else:
        for s in project.scenes:
            if s.video_url and s.video_url.startswith("gs://"):
                contents.append(
                    types.Part.from_uri(file_uri=s.video_url, mime_type="video/mp4")
                )
    storyboard_spec = {
        "project_name": project.name,
        "base_concept": project.base_concept,
        "continuity": project.continuity.dict() if project.continuity else {},
        "scenes": [
            {
                "scene_number": idx + 1,
                "scene_id": s.id,
                "timestamp_start": s.timestamp_start,
                "timestamp_end": s.timestamp_end,
                "visual_description": s.visual_description,
                "narration": s.narration or "",
                "speaker_notes": s.speaker_notes or "",
                "music_description": s.music_description or "",
            }
            for idx, s in enumerate(project.scenes)
        ],
    }
    contents.append(
        f"{FINISHED_VIDEO_EVAL_PROMPT}\n\nINTENDED STORYBOARD SPECIFICATION:\n{json.dumps(storyboard_spec, indent=2)}"
    )
    return contents


class GeminiService(GeminiVideoAnalysisMixin, GeminiGenerationMixin):
    def __init__(self, storage_svc: Any = None, firestore_svc: Any = None) -> None:
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
        self._clients: dict[str, genai.Client] = {self.location: self.client}

    def _get_client(self, region: str | None = None) -> genai.Client:
        loc = region or self.location
        if loc not in self._clients:
            self._clients[loc] = genai.Client(
                vertexai=True, project=self.project_id, location=loc
            )
        return self._clients[loc]

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
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        prompt = self.prompts.resolve_brief_prompt(
            concept,
            length,
            orientation,
            prompt_id,
            project_type or "advertizement",
            project,
        )
        schema = self.prompts.resolve_schema(
            schema_id, "project-analysis", "production-schema"
        )
        contents = _build_ref_contents(project, prompt)
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=schema
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
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

    async def review_storyboard(
        self,
        project_id: str,
        project: Project,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        """Audit the entire storyboard for continuity, physics, and speaker attribution."""
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        schema = load_schema("storyboard-review-schema")
        storyboard_payload = _build_storyboard_payload(project)
        prompt = (
            f"{STORYBOARD_REVIEWER_PROMPT}\n\n"
            f"STORYBOARD TO REVIEW:\n{json.dumps(storyboard_payload, indent=2)}"
        )
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, [prompt], cfg)
        usage = compute_usage(response, model_id)
        parsed_data = parse_review_response(
            response.parsed, project.scenes, usage=usage
        )
        return AIResponseWrapper(data=parsed_data, usage=usage)

    async def evaluate_finished_video(
        self,
        project_id: str,
        project: Project,
        video_gcs_uri: Optional[str] = None,
        iteration: int = 1,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        """Multimodal evaluation of the rendered video and scene clips against the storyboard."""
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        schema = load_schema("video-eval-schema")
        contents = _build_eval_contents(project, video_gcs_uri)
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        usage = compute_usage(response, model_id)
        report = parse_eval_response(
            response.parsed, project.scenes, iteration=iteration, usage=usage
        )
        return AIResponseWrapper(data={"eval_report": report}, usage=usage)

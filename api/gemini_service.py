"""Gemini service — video analysis, image generation, and content creation."""

import json
import logging
import os
from typing import Optional

from google import genai
from google.genai import types

from adapt_prompts import ADAPT_PROMPT_TEMPLATE, adapt_prompt_variables
from ai_helpers import (
    compute_image_usage,
    compute_usage,
    extract_image_from_response,
    load_schema,
    resolve_model,
    resolve_resource,
)
from brief_helpers import (
    parse_eval_response,
    parse_review_response,
    parse_scenes,
)
from helpers import gemini_call_with_retry
from models import AIResponseWrapper, Project, Scene, UsageMetrics
from prompt_resolver import PromptResolver, gcs_ref_url
from prompt_templates import (
    FINISHED_VIDEO_EVAL_PROMPT,
    SCENE_ANALYSIS_PROMPT,
    STORYBOARD_REVIEWER_PROMPT,
    build_collage_prompt,
)

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
        self._clients: dict[str, genai.Client] = {self.location: self.client}

    def _get_client(self, region: str | None = None) -> genai.Client:
        loc = region or self.location
        if loc not in self._clients:
            self._clients[loc] = genai.Client(
                vertexai=True, project=self.project_id, location=loc
            )
        return self._clients[loc]

    # ------------------------------------------------------------------
    # Brief analysis, Storyboard Review & Finished-Video Evaluation
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
            concept, length, orientation, prompt_id, project_type, project
        )
        schema = self.prompts.resolve_schema(
            schema_id, "project-analysis", "production-schema"
        )
        contents = _build_ref_contents(project, prompt)
        response = await gemini_call_with_retry(
            client,
            model_id,
            contents,
            types.GenerateContentConfig(
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

    async def review_storyboard(
        self,
        project_id: str,
        project: Project,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        """Audit the entire storyboard for speaker attribution, prop physics,
        character anatomy, environmental continuity, and transitions."""
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        schema = load_schema("storyboard-review-schema")
        storyboard_payload = {
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
        prompt = (
            f"{STORYBOARD_REVIEWER_PROMPT}\n\n"
            f"STORYBOARD TO REVIEW:\n{json.dumps(storyboard_payload, indent=2)}"
        )
        response = await gemini_call_with_retry(
            client,
            model_id,
            [prompt],
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=65536,
            ),
        )
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

        contents: list = []
        primary_uri = (
            video_gcs_uri or project.final_video_url or project.draft_video_url
        )
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
            f"{FINISHED_VIDEO_EVAL_PROMPT}\n\n"
            f"INTENDED STORYBOARD SPECIFICATION:\n{json.dumps(storyboard_spec, indent=2)}"
        )
        response = await gemini_call_with_retry(
            client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                max_output_tokens=65536,
            ),
        )
        usage = compute_usage(response, model_id)
        report = parse_eval_response(
            response.parsed, project.scenes, iteration=iteration, usage=usage
        )
        return AIResponseWrapper(data={"eval_report": report}, usage=usage)

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
        response = await gemini_call_with_retry(
            client,
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
            data={
                "image_url": url,
                "generated_prompt": prompt,
                "frame_position": frame_position,
            },
            usage=compute_image_usage(response, model_id),
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
        client = self._get_client(region)
        response = await gemini_call_with_retry(
            client,
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
            usage=compute_image_usage(response, model_id),
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
        prompt = self.prompts.require_prompt(prompt_id)
        schema = self.prompts.resolve_schema(
            schema_id, "key-moments", "key-moments-schema"
        )
        return await self._analyze_video(
            client, model_id, gcs_uri, mime_type, prompt, schema
        )

    async def analyze_video_for_thumbnails(
        self,
        gcs_uri: str,
        mime_type: str,
        prompt_id: str,
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
        prompt = self.prompts.require_prompt(prompt_id)
        schema = load_schema("thumbnail-analysis-schema")
        return await self._analyze_video(
            client, model_id, gcs_uri, mime_type, prompt, schema
        )

    async def analyze_video_focal_points(
        self,
        gcs_uri: str,
        mime_type: str = "video/mp4",
        prompt_id: str = "",
        content_type: str = "other",
        chirp_context: str = "",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        from reframe_strategies import resolve_prompt

        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
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
            client,
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
        cuts: Optional[list] = None,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        """Scene-based reframing analysis (used with MediaPipe + PySceneDetect)."""
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        prompt_text = SCENE_ANALYSIS_PROMPT
        prompt_variables = {"mode": "scene-based", "content_type": content_type}
        if cuts:
            cut_str = ", ".join(f"{c:.2f}s" for c in cuts)
            prompt_text = (
                f"=== DETECTED CUTS ===\nHard cuts at: {cut_str}\n"
                "Label each segment between consecutive cuts (and 0/end).\n\n"
                + prompt_text
            )
        if chirp_context:
            prompt_text = chirp_context + "\n\n" + prompt_text

        schema = load_schema("reframe-scenes-schema")
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        response = await gemini_call_with_retry(
            client,
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

    async def analyze_video_semantics(
        self,
        gcs_uri: str,
        cuts: Optional[list],
        chirp_context: str,
        duration: float,
        mime_type: str = "video/mp4",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> AIResponseWrapper:
        """Whole-video semantic pass (reframe Phase 4): per-shot categorical
        judgments — content kind, text importance, speaker screen positions.

        One flash-lite video+audio call (~100 tokens/s of video at 1 fps) that
        replaces the sparse thumbnail escalations for text/graphic/no-subject
        decisions. Returns the raw schema payload; ``reframe_semantic``
        validates and reconciles it against CPU facts. Coordinates are NEVER
        requested — video-mode spatial grounding is unreliable, and the CPU
        owns all geometry by design.
        """
        from reframe_semantic import SEMANTIC_MODEL, build_semantic_prompt

        model_id = model_id or SEMANTIC_MODEL
        client = self._get_client(region)
        prompt_text = build_semantic_prompt(cuts or [], chirp_context, duration)
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        # 1 fps sampling: shot-level labels need temporal coverage, not motion
        # detail. Audio stays on — it is what distinguishes a talking head from
        # a narrated poster and keys speakers to the Chirp labels.
        contents[0].video_metadata = types.VideoMetadata(fps=1)
        response = await gemini_call_with_retry(
            client,
            model_id,
            contents,
            types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=load_schema("reframe-semantic-schema"),
                max_output_tokens=65536,
            ),
        )
        data = response.parsed if isinstance(response.parsed, dict) else {"shots": []}
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

    async def decide_escalations(
        self,
        batches: list,
        video_path: str,
        region: Optional[str] = None,
        canvas: str = "9:16",
        active_area: Optional[dict] = None,
    ) -> AIResponseWrapper:
        """Pass 2: resolve the planner's escalated decision points with the
        decision model (gemini-3.5-flash).

        `batches` is `reframe_escalation.plan_batches(...)["batches"]` — request
        payloads, each a list of clustered decision points. Batches run
        SEQUENTIALLY (one request at a time; `gemini_call_with_retry` backs off on
        429). Thumbnails are decoded from the LOCAL source and sent inline — no
        video upload. Returns merged verdicts + summed usage. `active_area`
        trims baked-in source bars off the thumbnails so overlays line up with
        the plan's active-picture coordinates.
        """
        from reframe_decide import (
            DECISION_SCHEMA,
            build_cluster_block,
            build_decision_intro,
            render_decision_thumbs,
        )
        from reframe_escalation import DECISION_MODEL

        if not batches:
            return AIResponseWrapper(data={"verdicts": []}, usage=UsageMetrics())

        client = self._get_client(region)
        schema = load_schema(DECISION_SCHEMA)
        thumbs = render_decision_thumbs(
            video_path, [c for b in batches for c in b], active_area=active_area
        )
        intro = build_decision_intro(canvas)

        verdicts: list = []
        in_tok = out_tok = 0
        cost = 0.0
        for i, batch in enumerate(batches):
            contents: list = [intro]
            for c in batch:
                contents.append(build_cluster_block(c))
                for b in thumbs.get(c["key"], []):
                    contents.append(
                        types.Part.from_bytes(data=b, mime_type="image/jpeg")
                    )
            logger.info(
                f"reframe decide: batch {i + 1}/{len(batches)} "
                f"({len(batch)} points) via {DECISION_MODEL}"
            )
            response = await gemini_call_with_retry(
                client,
                DECISION_MODEL,
                contents,
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=8192,
                ),
            )
            data = response.parsed if isinstance(response.parsed, dict) else {}
            verdicts.extend(data.get("verdicts", []))
            u = compute_usage(response, DECISION_MODEL)
            in_tok += u.input_tokens
            out_tok += u.output_tokens
            cost += u.cost_usd
        usage = UsageMetrics(
            input_tokens=in_tok,
            output_tokens=out_tok,
            model_name=DECISION_MODEL,
            cost_usd=cost,
        )
        return AIResponseWrapper(data={"verdicts": verdicts}, usage=usage)

    async def analyze_video_for_promo(
        self,
        gcs_uri: str,
        mime_type: str = "video/mp4",
        target_duration: int = 60,
        prompt_id: str = "",
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
        prompt = self.prompts.resolve_promo_prompt(prompt_id, target_duration)
        schema = load_schema("promo-segments-schema")
        return await self._analyze_video(
            client, model_id, gcs_uri, mime_type, prompt, schema
        )

    # ------------------------------------------------------------------
    # Collage / overlay generation
    # ------------------------------------------------------------------

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
        contents = [
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
        contents = [
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

    # ------------------------------------------------------------------
    # Shared internal helpers
    # ------------------------------------------------------------------

    async def _analyze_video(
        self, client, model_id, gcs_uri, mime_type, prompt, schema
    ) -> AIResponseWrapper:
        """Video + prompt → structured JSON response."""
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt,
        ]
        response = await gemini_call_with_retry(
            client,
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
        self, client, model_id, contents, aspect_ratio, dest_folder
    ) -> AIResponseWrapper:
        """Contents → image generation → upload → response."""
        response = await gemini_call_with_retry(
            client,
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
            usage=compute_image_usage(response, model_id),
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _build_scene_prompt(
    scene: Scene,
    project: Optional[Project],
    orientation: Optional[str],
    frame_position: str = "start",
) -> str:
    """Build a flat scene keyframe prompt (start or end frame) from project context."""
    parts = []
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
    project,
    prompt,
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

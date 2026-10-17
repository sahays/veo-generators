"""Video analysis mixin for GeminiService (key moments, thumbnails, reframing, promos)."""

from __future__ import annotations

import logging
from typing import Any, Optional

from google.genai import types

from ai_helpers import compute_usage, load_schema, resolve_model, resolve_resource
from helpers import gemini_call_with_retry
from models import AIResponseWrapper, UsageMetrics
from prompt_templates import SCENE_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


def _build_scene_cuts_prompt(cuts: Optional[list], chirp_context: str) -> str:
    prompt_text = SCENE_ANALYSIS_PROMPT
    if cuts:
        cut_str = ", ".join(f"{c:.2f}s" for c in cuts)
        prompt_text = (
            f"=== DETECTED CUTS ===\nHard cuts at: {cut_str}\n"
            "Label each segment between consecutive cuts (and 0/end).\n\n" + prompt_text
        )
    if chirp_context:
        prompt_text = chirp_context + "\n\n" + prompt_text
    return prompt_text


def _build_escalation_batch_contents(
    intro: str, batch: list, thumbs: dict, build_cluster_block: Any
) -> list:
    contents: list = [intro]
    for c in batch:
        contents.append(build_cluster_block(c))
        for b in thumbs.get(c["key"], []):
            contents.append(types.Part.from_bytes(data=b, mime_type="image/jpeg"))
    return contents


class GeminiVideoAnalysisMixin:
    """Mixin providing video analysis methods for GeminiService."""

    firestore_svc: Any
    prompts: Any

    def _get_client(self, region: str | None = None) -> Any:
        raise NotImplementedError

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

    def _resolve_focal_points_prompt(
        self, prompt_id: str, content_type: str, chirp_context: str
    ) -> tuple[str, dict]:
        from reframe_strategies import resolve_prompt

        prompt_text, prompt_variables = None, {}
        if prompt_id and self.firestore_svc:
            prompt_text = resolve_resource(self.firestore_svc, prompt_id)
        if not prompt_text:
            prompt_text, prompt_variables = resolve_prompt(content_type)
        if chirp_context:
            prompt_text = chirp_context + "\n\n" + prompt_text
        return prompt_text, prompt_variables

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
        model_id = resolve_model(
            self.firestore_svc,
            "text",
            "OPTIMIZE_PROMPT_MODEL",
            "gemini-3.8-flash",
            model_id,
        )
        client = self._get_client(region)
        prompt_text, prompt_variables = self._resolve_focal_points_prompt(
            prompt_id, content_type, chirp_context
        )
        schema = load_schema("reframe-focal-points-schema")
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
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
        prompt_text = _build_scene_cuts_prompt(cuts, chirp_context)
        prompt_variables = {"mode": "scene-based", "content_type": content_type}
        schema = load_schema("reframe-scenes-schema")
        contents = [
            types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type),
            prompt_text,
        ]
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
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
        """Whole-video semantic pass (reframe Phase 4)."""
        from reframe_semantic import SEMANTIC_MODEL, build_semantic_prompt

        model_id = model_id or SEMANTIC_MODEL
        client = self._get_client(region)
        prompt_text = build_semantic_prompt(cuts or [], chirp_context, duration)
        part = types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type)
        part.video_metadata = types.VideoMetadata(fps=1)
        contents = [part, prompt_text]
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=load_schema("reframe-semantic-schema"),
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        data = response.parsed if isinstance(response.parsed, dict) else {"shots": []}
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

    async def _run_escalation_batch(
        self,
        client: Any,
        model: str,
        schema: dict,
        contents: list,
        idx: int,
        total: int,
        pts: int,
    ) -> tuple[list, UsageMetrics]:
        logger.info(
            f"reframe decide: batch {idx}/{total} ({pts} points) via {model}",
            extra={
                "who": "gemini_service",
                "where": "decide_escalations",
                "what": "run_batch",
                "why": f"batch_{idx}_{total}",
                "how": model,
            },
        )
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=8192,
        )
        response = await gemini_call_with_retry(client, model, contents, cfg)
        data = response.parsed if isinstance(response.parsed, dict) else {}
        return data.get("verdicts", []), compute_usage(response, model)

    async def decide_escalations(
        self,
        batches: list,
        video_path: str,
        region: Optional[str] = None,
        canvas: str = "9:16",
        active_area: Optional[dict] = None,
    ) -> AIResponseWrapper:
        """Pass 2: resolve the planner's escalated decision points with the decision model."""
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
            contents = _build_escalation_batch_contents(
                intro, batch, thumbs, build_cluster_block
            )
            b_verdicts, u = await self._run_escalation_batch(
                client,
                DECISION_MODEL,
                schema,
                contents,
                i + 1,
                len(batches),
                len(batch),
            )
            verdicts.extend(b_verdicts)
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

    async def _analyze_video(
        self,
        client: Any,
        model_id: str,
        gcs_uri: str,
        mime_type: str,
        prompt: str,
        schema: dict,
    ) -> AIResponseWrapper:
        """Video + prompt → structured JSON response."""
        contents = [types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type), prompt]
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=65536,
        )
        response = await gemini_call_with_retry(client, model_id, contents, cfg)
        data = response.parsed if isinstance(response.parsed, dict) else {}
        return AIResponseWrapper(data=data, usage=compute_usage(response, model_id))

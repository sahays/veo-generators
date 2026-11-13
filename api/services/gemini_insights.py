"""Gemini calls for the video insight features (scene analysis, engagement).

`GeminiInsightsMixin` is mixed into `GeminiService`. Both calls return
structured JSON and report the model's finish reason, so callers can tell a
truncated answer (`MAX_TOKENS`) from a complete one.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Optional

from google.genai import types

from ai_helpers import compute_usage, load_schema
from helpers import gemini_call_with_retry
from insight_prompts import build_timeline_prompt
from models import AIResponseWrapper, UsageMetrics
from timeline_windows import Window, covers_whole_video

logger = logging.getLogger(__name__)

INSIGHTS_MODEL_ENV = "VIDEO_INSIGHTS_MODEL"
DEFAULT_INSIGHTS_MODEL = "gemini-3.8-flash"
TIMELINE_SCHEMA = "video-timeline-schema"
FINISH_MAX_TOKENS = "MAX_TOKENS"
_TEMPERATURE = 0.2
_MAX_OUTPUT_TOKENS = 65536


class InsightResponse(AIResponseWrapper):
    """`AIResponseWrapper` plus how the model stopped.

    `data` is the parsed JSON object, or `{}` when the output was missing or
    not valid JSON. `finish_reason` is the model's finish reason name (`STOP`,
    `MAX_TOKENS`, `SAFETY`, ...), or `""` when the response had no candidate.
    """

    finish_reason: str = ""

    @property
    def truncated(self) -> bool:
        """True when the model ran out of output tokens."""
        return self.finish_reason == FINISH_MAX_TOKENS


def resolve_insights_model(model_id: Optional[str] = None) -> str:
    """Model for an insights call: explicit id, then env, then the default."""
    return model_id or os.getenv(INSIGHTS_MODEL_ENV) or DEFAULT_INSIGHTS_MODEL


def format_offset(seconds: float) -> str:
    """Seconds as the duration string `VideoMetadata` expects, e.g. `'90.5s'`."""
    text = f"{max(0.0, seconds):.3f}".rstrip("0").rstrip(".")
    return f"{text}s"


def build_video_part(
    gcs_uri: str, mime_type: str, window: Window, duration_sec: float
) -> types.Part:
    """Video part for one window; clipped with offsets unless it is the whole video."""
    part = types.Part.from_uri(file_uri=gcs_uri, mime_type=mime_type)
    if not covers_whole_video(window, duration_sec):
        part.video_metadata = types.VideoMetadata(
            start_offset=format_offset(window.start_sec),
            end_offset=format_offset(window.end_sec),
        )
    return part


def _json_config(schema: dict) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
        temperature=_TEMPERATURE,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
    )


def _finish_reason(response: Any) -> str:
    candidates = getattr(response, "candidates", None) or []
    reason = getattr(candidates[0], "finish_reason", None) if candidates else None
    if reason is None:
        return ""
    return str(getattr(reason, "name", reason))


def _parsed_json(response: Any) -> dict:
    """The response as a JSON object; `{}` when it is absent or malformed."""
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    try:
        loaded = json.loads(response.text or "")
    except (TypeError, ValueError, AttributeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def to_insight_response(response: Any, model_id: str) -> InsightResponse:
    """Wrap a raw Gemini response: parsed data, usage and finish reason."""
    has_usage = getattr(response, "usage_metadata", None) is not None
    usage = (
        compute_usage(response, model_id)
        if has_usage
        else UsageMetrics(model_name=model_id)
    )
    result = InsightResponse(
        data=_parsed_json(response),
        usage=usage,
        finish_reason=_finish_reason(response),
    )
    if not result.data or result.truncated:
        logger.warning(
            f"Insights response unusable (finish_reason={result.finish_reason or 'none'})",
            extra={
                "who": "gemini_insights",
                "where": "to_insight_response",
                "what": f"finish_reason={result.finish_reason or 'none'}",
                "why": "truncated_or_unparseable_output",
                "how": model_id,
            },
        )
    return result


class GeminiInsightsMixin:
    """Structured-output Gemini calls shared by scene analysis and engagement."""

    _get_client: Callable[..., Any]

    async def analyze_timeline_window(
        self,
        gcs_uri: str,
        mime_type: str,
        window: Window,
        duration_sec: float,
        cuts: list[float],
        focus: str = "",
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> InsightResponse:
        """Analyse one window of a video into the timeline schema.

        A window that is the whole video is sent without clip offsets; any
        other window is clipped with `VideoMetadata` offsets. `focus` is
        untrusted user text and reaches the model only as delimited data.
        Check `finish_reason` / `truncated` and an empty `data` before using
        the result.
        """
        model = resolve_insights_model(model_id)
        contents = [
            build_video_part(gcs_uri, mime_type, window, duration_sec),
            build_timeline_prompt(window, duration_sec, cuts, focus),
        ]
        config = _json_config(load_schema(TIMELINE_SCHEMA))
        client = self._get_client(region)
        response = await gemini_call_with_retry(client, model, contents, config)
        return to_insight_response(response, model)

    async def generate_insight_json(
        self,
        prompt: str,
        schema: dict,
        model_id: Optional[str] = None,
        region: Optional[str] = None,
    ) -> InsightResponse:
        """Text-only structured call: `prompt` in, a JSON object matching `schema` out.

        Generic by design (no video, no feature-specific prompt). Returns `{}`
        in `data` when the model output is missing, truncated mid-object or not
        valid JSON; it does not raise for those cases, so callers decide whether
        an empty answer is fatal.
        """
        model = resolve_insights_model(model_id)
        client = self._get_client(region)
        response = await gemini_call_with_retry(
            client, model, [prompt], _json_config(schema)
        )
        return to_insight_response(response, model)

"""Reframe / Orientations specialist (`reframe_agent`) — converts horizontal videos to vertical/portrait."""

from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    build_specialist,
    display_name,
    make_check_job_status,
    make_list_available_videos,
    propose_job,
    resolve_or_pick,
    source_picker_fallback,
)

_REFRAME_ROLE = (
    "You are the Orientations & Reframe Specialist (`reframe_agent`). "
    "You reframe horizontal videos into vertical/portrait orientations using subject tracking.\n"
    "Before proposing a reframe job:\n"
    "- If the user hasn't specified a video, you can either call list_available_videos() "
    "or call propose_reframe(gcs_uri='') to render an interactive A2UI card with an inline video selector.\n"
    "- Call list_content_types() to inspect valid content types and CV strategies.\n"
    "IMPORTANT: Always use propose_reframe() so the user can review and confirm."
)


async def content_type_index(invite_code: str) -> dict:
    """Fetch valid content types once and key by id."""
    types = await agent_tools.list_content_types(invite_code)
    if not isinstance(types, list):
        return {}
    return {t["id"]: t for t in types}


async def _format_content_types(invite_code: str) -> str:
    by_id = await content_type_index(invite_code)
    if not by_id:
        return "No content types found."
    lines = [
        f"- {t['id']}: {t.get('description', '')} (strategy: {t.get('cv_strategy', '')})"
        for t in by_id.values()
    ]
    return "Available content types:\n" + "\n".join(lines)


async def _do_propose_reframe(
    invite_code: str, gcs_uri: str, content_type: str, source_filename: str
) -> str:
    resolved_uri = await resolve_or_pick(invite_code, gcs_uri, kind="video")
    if not resolved_uri:
        return source_picker_fallback("video")
    by_id = await content_type_index(invite_code)
    if by_id and content_type not in by_id:
        return (
            f"Invalid content_type '{content_type}'. Valid options: {', '.join(by_id)}"
        )
    match = by_id.get(content_type) if by_id else None
    label = match.get("description", content_type) if match else content_type
    return propose_job(
        "reframe",
        "Reframe video to vertical",
        {
            "gcs_uri": resolved_uri,
            "source_filename": source_filename,
            "content_type": content_type,
            "blurred_bg": False,
        },
        {
            "source_name": display_name(source_filename, resolved_uri),
            "content_type_label": label,
        },
    )


def _make_reframe_tools(invite_code: str) -> list:
    async def list_recent_reframes(limit: int = 5) -> Any:
        """List the most recent video reframe jobs."""
        return await agent_tools.list_recent_reframes(invite_code, limit)

    async def list_content_types() -> str:
        """List valid content types for reframing. Call before proposing a reframe."""
        return await _format_content_types(invite_code)

    async def propose_reframe(
        gcs_uri: str, content_type: str = "other", source_filename: str = ""
    ) -> str:
        """Propose a video reframe job. Returns an interactive A2UI confirmation card."""
        return await _do_propose_reframe(
            invite_code, gcs_uri, content_type, source_filename
        )

    return [
        list_recent_reframes,
        list_content_types,
        propose_reframe,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_reframe_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "reframe_agent",
        _REFRAME_ROLE,
        _make_reframe_tools(invite_code),
        model=model,
        tier="specialist",
    )

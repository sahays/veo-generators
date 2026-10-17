"""Thumbnails specialist (`thumbnails_agent`) — video thumbnail analysis, frame capture, and collage generation."""

from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    build_specialist,
    make_check_job_status,
    make_list_available_videos,
    make_prompt_lister,
    make_prompt_video_proposer,
)

_THUMBNAILS_ROLE = (
    "You are the Thumbnail Designer Specialist (`thumbnails_agent`). "
    "You analyze videos for best thumbnail timestamps, capture high-res frames, and generate thumbnail collages.\n"
    "- Call list_available_videos() for the source video.\n"
    "- Call list_thumbnail_prompts() so the user picks a Thumbnail analysis prompt.\n"
    "- Call propose_thumbnails() to present the interactive A2UI confirmation card.\n"
    "- For an analyzed thumbnail job, you can also trigger capture-frames or generate-collage via advance_thumbnail_step()."
)


def _make_thumbnails_tools(invite_code: str) -> list:
    async def list_recent_thumbnails(limit: int = 5) -> Any:
        """List the most recent thumbnail jobs."""
        return await agent_tools.list_recent_thumbnails(invite_code, limit)

    propose_thumbnails = make_prompt_video_proposer(
        invite_code,
        "thumbnails",
        "Generate thumbnails",
        "propose_thumbnails",
        "Propose thumbnail generation/analysis. Returns an interactive A2UI confirmation card.",
    )

    async def advance_thumbnail_step(record_id: str, step: str) -> Any:
        """Trigger 'capture-frames' or 'generate-collage' on an existing thumbnail record."""
        if step not in ("capture-frames", "generate-collage"):
            return "Invalid step. Choose 'capture-frames' or 'generate-collage'."
        return await agent_tools.trigger_thumbnail_step(invite_code, record_id, step)

    return [
        list_recent_thumbnails,
        make_prompt_lister(
            invite_code, "thumbnails", "list_thumbnail_prompts", "Thumbnail"
        ),
        propose_thumbnails,
        advance_thumbnail_step,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_thumbnails_agent(
    invite_code: str, model: Optional[Gemini] = None
) -> LlmAgent:
    return build_specialist(
        "thumbnails_agent",
        _THUMBNAILS_ROLE,
        _make_thumbnails_tools(invite_code),
        model=model,
        tier="specialist",
    )

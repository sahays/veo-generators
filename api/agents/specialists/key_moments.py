"""Key Moments specialist (`key_moments_agent`) — analyzes videos to extract timestamped key moments."""

from typing import Optional

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

_KEY_MOMENTS_ROLE = (
    "You are the Key Moments Video Intelligence Specialist (`key_moments_agent`). "
    "You analyze videos to detect timestamped highlights and key moments.\n"
    "- Call list_available_videos() if the user needs to choose a video source.\n"
    "- Call list_key_moment_prompts() so the user can choose a Key Moments analysis prompt.\n"
    "- Call propose_key_moments() to present the interactive A2UI confirmation card."
)


def _make_key_moments_tools(invite_code: str) -> list:
    async def list_recent_key_moments(limit: int = 5):
        """List the most recent key moments analysis jobs."""
        return await agent_tools.list_recent_key_moments(invite_code, limit)

    propose_key_moments = make_prompt_video_proposer(
        invite_code,
        "key_moments",
        "Analyze key moments",
        "propose_key_moments",
        "Propose a Key Moments analysis. Returns an interactive A2UI confirmation card.",
    )

    return [
        list_recent_key_moments,
        make_prompt_lister(
            invite_code, "key-moments", "list_key_moment_prompts", "Key Moments"
        ),
        propose_key_moments,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_key_moments_agent(
    invite_code: str, model: Optional[Gemini] = None
) -> LlmAgent:
    return build_specialist(
        "key_moments_agent",
        _KEY_MOMENTS_ROLE,
        _make_key_moments_tools(invite_code),
        model=model,
        tier="specialist",
    )

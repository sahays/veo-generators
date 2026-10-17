"""Promo specialist (`promo_agent`) — generates promotional video cutdowns and title cards."""

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

_PROMO_ROLE = (
    "You are the Promo Video Specialist (`promo_agent`). "
    "You create promotional trailer/cutdown videos from source videos or productions.\n"
    "- Call list_available_videos() if the user needs to pick a source video.\n"
    "- Call propose_promo() to create an interactive A2UI confirmation card where the user can adjust duration (60s-180s), text overlays, and thumbnail cards."
)


async def _do_propose_promo(
    invite_code: str,
    gcs_uri: str,
    target_duration: int,
    source_filename: str,
    text_overlay: bool,
) -> str:
    resolved_uri = await resolve_or_pick(invite_code, gcs_uri, kind="video")
    if not resolved_uri:
        return source_picker_fallback("video")
    return propose_job(
        "promo",
        f"Create {target_duration // 60}-min promo",
        {
            "gcs_uri": resolved_uri,
            "source_filename": source_filename,
            "target_duration": target_duration,
            "text_overlay": text_overlay,
            "generate_thumbnail": False,
        },
        {"source_name": display_name(source_filename, resolved_uri)},
    )


def _make_promo_tools(invite_code: str) -> list:
    async def list_recent_promos(limit: int = 5) -> Any:
        """List the most recent promotional video jobs."""
        return await agent_tools.list_recent_promos(invite_code, limit)

    async def propose_promo(
        gcs_uri: str,
        target_duration: int = 60,
        source_filename: str = "",
        text_overlay: bool = False,
    ) -> str:
        """Propose a new promo cutdown job. Returns an interactive A2UI confirmation card."""
        return await _do_propose_promo(
            invite_code, gcs_uri, target_duration, source_filename, text_overlay
        )

    return [
        list_recent_promos,
        propose_promo,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_promo_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "promo_agent",
        _PROMO_ROLE,
        _make_promo_tools(invite_code),
        model=model,
        tier="specialist",
    )

"""Marketer specialist — promo videos and multi-platform adapts."""

from typing import List

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    build_specialist,
    display_name,
    make_check_job_status,
    make_list_available_videos,
    propose_job,
)

_MARKETER_ROLE = (
    "You are the Marketing Expert. You create promos and social adaptations.\n"
    "IMPORTANT: Call list_adapt_options() before creating adapts to show the user "
    "valid aspect ratios and preset bundles.\n"
    "IMPORTANT: Use propose_* tools to create confirmation cards. "
    "Never execute jobs directly — always let the user review and confirm first."
)


def _make_marketer_tools(invite_code: str) -> list:
    async def list_recent_promos(limit: int = 5):
        """List the most recent promotional video jobs."""
        return await agent_tools.list_recent_promos(invite_code, limit)

    async def list_recent_adapts(limit: int = 5):
        """List the most recent social media adaptation jobs."""
        return await agent_tools.list_recent_adapts(invite_code, limit)

    async def list_adapt_options():
        """List valid aspect ratios and preset bundles for adapt jobs."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        if not isinstance(data, dict):
            return "Could not fetch adapt options."
        lines: list[str] = []
        bundles = data.get("preset_bundles", {})
        if bundles:
            lines.append("Preset bundles:")
            for k, v in bundles.items():
                lines.append(f"  - {k} ({v['name']}): {', '.join(v['ratios'])}")
        ratios = data.get("ratios", [])
        if ratios:
            lines.append(f"All valid ratios: {', '.join(ratios)}")
        return "\n".join(lines)

    async def propose_promo(
        gcs_uri: str,
        target_duration: int = 60,
        source_filename: str = "",
        text_overlay: bool = False,
    ):
        """Propose a new promo. Returns a confirmation card."""
        return propose_job(
            "promo",
            f"Create {target_duration // 60}-min promo",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "target_duration": target_duration,
                "text_overlay": text_overlay,
                "generate_thumbnail": False,
            },
            {"source_name": display_name(source_filename, gcs_uri)},
        )

    async def propose_adapts(
        gcs_uri: str, aspect_ratios: List[str], source_filename: str = ""
    ):
        """Propose adapting a video for multiple platforms. Returns a confirmation card."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        valid = data.get("ratios", []) if isinstance(data, dict) else []
        if valid:
            valid_set = set(valid)
            invalid = [r for r in aspect_ratios if r not in valid_set]
            if invalid:
                return (
                    f"Invalid aspect ratios: {', '.join(invalid)}. "
                    f"Valid options: {', '.join(valid)}"
                )
        return propose_job(
            "adapts",
            f"Adapt for {len(aspect_ratios)} platforms",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "aspect_ratios": aspect_ratios,
            },
            {"source_name": display_name(source_filename, gcs_uri)},
        )

    return [
        list_recent_promos,
        list_recent_adapts,
        list_adapt_options,
        propose_promo,
        propose_adapts,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_marketer_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return build_specialist(
        "marketer", _MARKETER_ROLE, _make_marketer_tools(invite_code), model
    )

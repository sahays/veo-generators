"""Adapts specialist (`adapts_agent`) — multi-platform social image adaptations."""

from typing import List, Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    build_specialist,
    display_name,
    make_check_job_status,
    make_list_available_images,
    propose_job,
    resolve_or_pick,
    source_picker_fallback,
)

_ADAPTS_ROLE = (
    "You are the Social Media Adapts Specialist (`adapts_agent`). "
    "You adapt and outpaint source IMAGES across multiple aspect ratios (16:9, 9:16, 1:1, 4:5, 4:3, 3:4).\n"
    "- Call list_available_images() for the source image (adapts require an IMAGE, not a video).\n"
    "- Call list_adapt_options() to inspect valid aspect ratios and preset bundles.\n"
    "- Call propose_adapts() to create an interactive A2UI confirmation card."
)


def _make_adapts_tools(invite_code: str) -> list:
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

    async def propose_adapts(
        gcs_uri: str, aspect_ratios: List[str], source_filename: str = ""
    ):
        """Propose adapting an image for multiple platforms. Returns an interactive A2UI confirmation card."""
        resolved_uri = await resolve_or_pick(invite_code, gcs_uri, kind="image")
        if not resolved_uri:
            return source_picker_fallback("image")
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
                "gcs_uri": resolved_uri,
                "source_filename": source_filename,
                "aspect_ratios": aspect_ratios,
            },
            {"source_name": display_name(source_filename, resolved_uri)},
        )

    return [
        list_recent_adapts,
        list_adapt_options,
        propose_adapts,
        make_list_available_images(invite_code),
        make_check_job_status(invite_code),
    ]


def create_adapts_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "adapts_agent",
        _ADAPTS_ROLE,
        _make_adapts_tools(invite_code),
        model=model,
        tier="specialist",
    )

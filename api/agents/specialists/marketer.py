"""Marketer specialist — promo videos and multi-platform adapts."""

from typing import List

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    _request_context,
    build_specialist,
    display_name,
    make_check_job_status,
    make_list_available_images,
    make_list_available_videos,
    propose_job,
    resolve_source_uri,
)


def _fallback(kind: str) -> str:
    noun = "images" if kind == "image" else "videos"
    selector = "image" if kind == "image" else "video"
    return (
        f"I couldn't match that to one of your {noun}. I've opened the "
        f"{selector} selector — pick the source and I'll continue."
    )


async def _resolve_or_pick(
    invite_code: str, gcs_uri: str, kind: str = "video"
) -> str | None:
    resolved = await resolve_source_uri(invite_code, gcs_uri, kind=kind)
    if not resolved:
        _request_context.get().update(
            {"source_picker": "image" if kind == "image" else True}
        )
    return resolved


_MARKETER_ROLE = (
    "You are the Marketing Expert. You create promos (from a VIDEO) and social "
    "adaptations (adapts, which resize an IMAGE).\n"
    "Open the right picker for the source before proposing:\n"
    "- Promo: call list_available_videos() for the source video, then propose_promo().\n"
    "- Adapt: call list_available_images() for the source image (adapts need an "
    "image, NOT a video or production), then list_adapt_options() to show valid "
    "aspect ratios / preset bundles, then propose_adapts().\n"
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
        gcs_uri = await _resolve_or_pick(invite_code, gcs_uri, kind="video")
        if not gcs_uri:
            return _fallback("video")
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
        """Propose adapting an image for multiple platforms. Returns a confirmation card."""
        gcs_uri = await _resolve_or_pick(invite_code, gcs_uri, kind="image")
        if not gcs_uri:
            return _fallback("image")
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
        make_list_available_images(invite_code),
        make_check_job_status(invite_code),
    ]


def create_marketer_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return build_specialist(
        "marketer", _MARKETER_ROLE, _make_marketer_tools(invite_code), model
    )

"""Dubbing specialist (`dubbing_agent`) — multi-language video dubbing and SRT subtitles."""

from typing import Any, List, Optional

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

_DUBBING_ROLE = (
    "You are the Multi-Language Dubbing Specialist (`dubbing_agent`). "
    "You translate and dub videos into up to 4 target languages with synchronized audio and SRT subtitles.\n"
    "- Call list_dubbing_languages() to discover supported language codes (e.g. es-US, hi-IN, fr-FR, de-DE, ja-JP, pt-BR, ar-XA, ko-KR).\n"
    "- Call list_available_videos() if the user needs to choose a source video.\n"
    "- Call propose_dubbing() to present an interactive A2UI confirmation card where the user can toggle target languages and confirm.\n"
    "- You can also retry unfinished variants on an existing job via retry_failed_dubbing()."
)


async def _format_dubbing_languages(invite_code: str) -> str:
    langs = await agent_tools.list_dubbing_languages(invite_code)
    if not isinstance(langs, list) or not langs:
        return "Could not fetch dubbing languages."
    lines = [
        f"- {item.get('code')}: {item.get('label')} (region: {item.get('region', 'global')})"
        for item in langs
    ]
    return "Supported dubbing languages (max 4 per job):\n" + "\n".join(lines)


async def _do_propose_dubbing(
    invite_code: str, gcs_uri: str, target_languages: List[str], source_filename: str
) -> str:
    resolved_uri = await resolve_or_pick(invite_code, gcs_uri, kind="video")
    if not resolved_uri:
        return source_picker_fallback("video")
    langs = await agent_tools.list_dubbing_languages(invite_code)
    valid_codes = (
        {item.get("code"): item.get("label", item.get("code")) for item in langs}
        if isinstance(langs, list)
        else {}
    )
    cleaned = [c for c in dict.fromkeys(target_languages) if c]
    if valid_codes:
        invalid = [c for c in cleaned if c not in valid_codes]
        if invalid:
            return f"Unsupported language code(s): {', '.join(invalid)}. Valid codes: {', '.join(valid_codes.keys())}"
    labels = [valid_codes.get(c, c) for c in cleaned]
    return propose_job(
        "dubbing",
        f"Dub video into {len(cleaned)} language(s)",
        {
            "gcs_uri": resolved_uri,
            "target_languages": cleaned,
            "source_filename": source_filename,
        },
        {
            "source_name": display_name(source_filename, resolved_uri),
            "languages_label": ", ".join(labels),
        },
    )


def _make_dubbing_tools(invite_code: str) -> list:
    async def list_dubbing_languages() -> str:
        """List all target languages supported by the Dubbing service."""
        return await _format_dubbing_languages(invite_code)

    async def list_recent_dubbing(limit: int = 5) -> Any:
        """List the most recent video dubbing jobs."""
        return await agent_tools.list_recent_dubbing(invite_code, limit)

    async def propose_dubbing(
        gcs_uri: str, target_languages: List[str], source_filename: str = ""
    ) -> str:
        """Propose a multi-language video dubbing job. Returns an interactive A2UI confirmation card."""
        return await _do_propose_dubbing(
            invite_code, gcs_uri, target_languages, source_filename
        )

    async def retry_failed_dubbing(record_id: str) -> Any:
        """Retry failed or unfinished language variants on an existing dubbing job."""
        return await agent_tools.retry_dubbing(invite_code, record_id)

    return [
        list_dubbing_languages,
        list_recent_dubbing,
        propose_dubbing,
        retry_failed_dubbing,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_dubbing_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "dubbing_agent",
        _DUBBING_ROLE,
        _make_dubbing_tools(invite_code),
        model=model,
        tier="specialist",
    )

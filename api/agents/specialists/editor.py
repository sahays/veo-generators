"""Editor specialist — reframe, key moments, thumbnails."""

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    _request_context,
    build_specialist,
    display_name,
    make_check_job_status,
    make_list_available_videos,
    make_prompt_lister,
    propose_job,
    resolve_prompt_name,
    resolve_source_uri,
)

# Returned when a source reference can't be matched to a real gs:// video, so
# the agent opens the picker instead of proposing a job with a bad URI.
_SOURCE_PICKER_FALLBACK = (
    "I couldn't match that to one of your videos. I've opened the video "
    "selector — pick the source and I'll continue."
)


async def _resolve_or_pick(invite_code: str, gcs_uri: str) -> str | None:
    """Resolve a source reference to a gs:// URI, or open the picker and bail."""
    resolved = await resolve_source_uri(invite_code, gcs_uri)
    if not resolved:
        _request_context.get().update({"source_picker": True})
    return resolved


_EDITOR_ROLE = (
    "You are the Video Editor. You process existing videos (reframe, key moments, thumbnails).\n"
    "Before proposing a job, gather its inputs by opening pickers for the user — never ask "
    "them to type a URI or prompt ID:\n"
    "- Reframe: call list_available_videos() for the source, then list_content_types() to pick "
    "the content type, then propose_reframe().\n"
    "- Key moments: call list_available_videos() for the source, then list_key_moment_prompts() "
    "so the user picks an analysis prompt, then propose_key_moments().\n"
    "- Thumbnails: call list_available_videos() for the source, then list_thumbnail_prompts() so "
    "the user picks an analysis prompt, then propose_thumbnails(). After the thumbnail job is "
    "confirmed, tell the user to open the result to capture frames and generate the final "
    "collage on the Thumbnails page.\n"
    "IMPORTANT: Use propose_* tools to create confirmation cards. "
    "Never execute jobs directly — always let the user review and confirm first."
)


async def _content_type_index(invite_code: str) -> dict:
    """Fetch valid content types once and key by id; lookups are O(1)
    instead of scanning the list per propose call."""
    types = await agent_tools.list_content_types(invite_code)
    if not isinstance(types, list):
        return {}
    return {t["id"]: t for t in types}


def _make_editor_tools(invite_code: str) -> list:
    async def list_recent_reframes(limit: int = 5):
        """List the most recent video reframe jobs."""
        return await agent_tools.list_recent_reframes(invite_code, limit)

    async def list_recent_key_moments(limit: int = 5):
        """List the most recent key moments analysis jobs."""
        return await agent_tools.list_recent_key_moments(invite_code, limit)

    async def list_recent_thumbnails(limit: int = 5):
        """List the most recent thumbnail jobs."""
        return await agent_tools.list_recent_thumbnails(invite_code, limit)

    async def list_content_types():
        """List valid content types for reframing. Call before proposing a reframe."""
        by_id = await _content_type_index(invite_code)
        if not by_id:
            return "No content types found."
        lines = [
            f"- {t['id']}: {t.get('description', '')} (strategy: {t.get('cv_strategy', '')})"
            for t in by_id.values()
        ]
        return "Available content types:\n" + "\n".join(lines)

    async def propose_reframe(
        gcs_uri: str, content_type: str = "other", source_filename: str = ""
    ):
        """Propose a reframe. Returns a confirmation card."""
        gcs_uri = await _resolve_or_pick(invite_code, gcs_uri)
        if not gcs_uri:
            return _SOURCE_PICKER_FALLBACK
        by_id = await _content_type_index(invite_code)
        if by_id and content_type not in by_id:
            return (
                f"Invalid content_type '{content_type}'. "
                f"Valid options: {', '.join(by_id)}"
            )
        match = by_id.get(content_type) if by_id else None
        label = match.get("description", content_type) if match else content_type
        return propose_job(
            "reframe",
            "Reframe video to vertical",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "content_type": content_type,
                "blurred_bg": False,
            },
            {
                "source_name": display_name(source_filename, gcs_uri),
                "content_type_label": label,
            },
        )

    async def propose_key_moments(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose a Key Moments analysis. Returns a confirmation card."""
        gcs_uri = await _resolve_or_pick(invite_code, gcs_uri)
        if not gcs_uri:
            return _SOURCE_PICKER_FALLBACK
        return propose_job(
            "key_moments",
            "Analyze key moments",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            {
                "prompt_name": await resolve_prompt_name(invite_code, prompt_id),
                "source_name": display_name(source_filename, gcs_uri),
            },
        )

    async def propose_thumbnails(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose thumbnail generation/analysis. Returns a confirmation card."""
        gcs_uri = await _resolve_or_pick(invite_code, gcs_uri)
        if not gcs_uri:
            return _SOURCE_PICKER_FALLBACK
        return propose_job(
            "thumbnails",
            "Generate thumbnails",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            {
                "prompt_name": await resolve_prompt_name(invite_code, prompt_id),
                "source_name": display_name(source_filename, gcs_uri),
            },
        )

    return [
        list_recent_reframes,
        list_recent_key_moments,
        list_recent_thumbnails,
        list_content_types,
        make_prompt_lister(
            invite_code, "key-moments", "list_key_moment_prompts", "Key Moments"
        ),
        make_prompt_lister(
            invite_code, "thumbnails", "list_thumbnail_prompts", "Thumbnail"
        ),
        propose_reframe,
        propose_key_moments,
        propose_thumbnails,
        make_list_available_videos(invite_code),
        make_check_job_status(invite_code),
    ]


def create_editor_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return build_specialist(
        "editor", _EDITOR_ROLE, _make_editor_tools(invite_code), model
    )

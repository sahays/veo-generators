"""System lookup tools — content types, aspect ratios, prompt categories, prompts."""

from typing import List, Optional

from ._client import api_call


async def list_content_types(invite_code: str) -> List[dict]:
    """Return valid content types for video reframing."""
    return await api_call("GET", "/api/v1/system/lookups/content-types", invite_code)


async def list_aspect_ratios(invite_code: str) -> dict:
    """Return valid aspect ratios and preset bundles for adapts."""
    return await api_call("GET", "/api/v1/system/lookups/aspect-ratios", invite_code)


async def list_prompt_categories(invite_code: str) -> List[dict]:
    """Return distinct prompt categories from the database."""
    return await api_call(
        "GET", "/api/v1/system/lookups/prompt-categories", invite_code
    )


async def list_system_prompts(
    invite_code: str, category: Optional[str] = None
) -> List[dict]:
    """List available system prompts/resources, optionally filtered by category."""
    params: dict = {"type": "prompt"}
    if category:
        params["category"] = category
    return await api_call(
        "GET", "/api/v1/system/resources", invite_code, params=params
    )

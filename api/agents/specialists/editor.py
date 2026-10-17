"""Backward-compatible Editor aggregator re-exporting tools from reframe, key_moments, and thumbnails specialists."""

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools  # noqa: F401
from .._shared import build_specialist
from .key_moments import _make_key_moments_tools
from .reframe import _make_reframe_tools
from .thumbnails import _make_thumbnails_tools

_EDITOR_ROLE = "You are the Video Editor. You process existing videos (reframe, key moments, thumbnails)."


def _make_editor_tools(invite_code: str) -> list:
    seen: set[str] = set()
    merged: list = []
    for func in (
        _make_reframe_tools(invite_code)
        + _make_key_moments_tools(invite_code)
        + _make_thumbnails_tools(invite_code)
    ):
        name = getattr(func, "__name__", "")
        if name not in seen:
            seen.add(name)
            merged.append(func)
    return merged


def create_editor_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "editor",
        _EDITOR_ROLE,
        _make_editor_tools(invite_code),
        model=model,
        tier="specialist",
    )

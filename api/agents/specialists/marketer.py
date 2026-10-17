"""Backward-compatible Marketer aggregator re-exporting tools from promo and adapts specialists."""

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools  # noqa: F401
from .._shared import build_specialist
from .adapts import _make_adapts_tools
from .promo import _make_promo_tools

_MARKETER_ROLE = "You are the Marketing Expert. You create promos (from a VIDEO) and social adaptations (from an IMAGE)."


def _make_marketer_tools(invite_code: str) -> list:
    seen: set[str] = set()
    merged: list = []
    for func in _make_promo_tools(invite_code) + _make_adapts_tools(invite_code):
        name = getattr(func, "__name__", "")
        if name not in seen:
            seen.add(name)
            merged.append(func)
    return merged


def create_marketer_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "marketer",
        _MARKETER_ROLE,
        _make_marketer_tools(invite_code),
        model=model,
        tier="specialist",
    )

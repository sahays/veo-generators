"""Aanya orchestrator — routes user intent to specialists, handles pricing inline.

Specialists live under `agents/specialists/*`. Shared scaffolding (model
factory, request-scoped context, scope policy) is in `agents/_shared.py`.
"""

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from . import tools as agent_tools
from ._shared import (
    STRICT_SCOPE_INSTRUCTION,
    create_model,
    get_agent_context,
    reset_agent_context,
)
from .specialists import (
    create_director_agent,
    create_editor_agent,
    create_marketer_agent,
)

# Public re-exports so existing `from agents.factory import …` callers
# continue to work without touching their imports.
__all__ = [
    "create_orchestrator",
    "create_director_agent",
    "create_editor_agent",
    "create_marketer_agent",
    "get_agent_context",
]

_ORCHESTRATOR_ROLE = (
    "Introduce yourself as Aanya, the Veo AI Orchestrator. "
    "Delegate based on intent:\n"
    "- New projects, scripts, system prompts/templates, prompt categories: 'director'\n"
    "- Editing, reframing, thumbnails, key moments: 'editor'\n"
    "- Promo video generation, marketing, social adaptations: 'marketer'\n"
    "- Pricing, rates, cost estimates, cost breakdown for a job: handle "
    "yourself using get_pricing_rates / get_feature_services / "
    "estimate_cost / get_job_cost. Do NOT delegate pricing questions.\n\n"
    "IMPORTANT: When the user asks to list or browse 'prompts' or 'templates', "
    "delegate to 'director' (NOT 'marketer'). 'Prompts' are system prompt templates "
    "managed by the director. 'Promos' are promotional video jobs managed by the marketer.\n"
    "When a sub-agent proposes a job, relay their response. A confirmation card "
    "will appear automatically for the user to review and confirm.\n"
    "For cost questions:\n"
    "- If the user references a specific record ID, call get_job_cost(feature, id) directly.\n"
    "- If the user says 'last/previous/most recent X' or 'my X' without an ID, "
    "first call list_recent_jobs(feature, limit=1) to resolve the ID, then "
    "call get_job_cost. Do NOT ask the user for an ID — look it up yourself.\n"
    "- If the user asks to list or compare multiple recent jobs, call "
    "list_recent_jobs, then get_job_cost for each, and present a table.\n"
    "- If the user asks 'how much would X cost' without a record, use estimate_cost.\n"
    "- If the user asks about rates or which services are billed, use "
    "get_pricing_rates or get_feature_services.\n"
    "- Always surface the pricing_confidence field when you return a job cost — "
    "say 'this is approximate' when it's not 'high'.\n"
    "- When showing multiple records, prefer a markdown table (GFM tables are "
    "supported in the chat UI).\n"
    "Always be helpful, friendly, and professional."
)


_ESTIMATE_FIELDS = (
    "scene_count",
    "video_length_seconds",
    "variant_count",
    "source_duration_seconds",
    "segment_count",
    "has_title_card",
    "thumbnail_count",
)


def _make_orchestrator_tools(invite_code: str) -> list:
    async def get_pricing_rates():
        """Return the current pricing catalog — per-token rates for Gemini text
        and image models, per-second Veo rates, and per-minute flat services
        (Cloud Transcoder, Speech V2 diarization). Use when the user asks
        about rates, what a service costs per unit, or which models exist."""
        return await agent_tools.get_pricing_rates(invite_code)

    async def get_feature_services():
        """Return the list of services each feature consumes (production,
        adapts, reframe, promo, key_moments, thumbnails) with rates inlined.
        Use when the user asks 'what does feature X use?' or 'what services
        are billed for Y?'."""
        return await agent_tools.get_feature_services(invite_code)

    async def estimate_cost(
        feature: str,
        scene_count: Optional[int] = None,
        video_length_seconds: Optional[float] = None,
        variant_count: Optional[int] = None,
        source_duration_seconds: Optional[float] = None,
        segment_count: Optional[int] = None,
        has_title_card: Optional[bool] = None,
        thumbnail_count: Optional[int] = None,
    ):
        """Estimate the cost of a job BEFORE it runs. `feature` must be one of
        production/adapts/reframe/promo/key_moments/thumbnails. Pass the
        feature-specific inputs (scene_count, video_length_seconds,
        variant_count, source_duration_seconds, segment_count, has_title_card,
        thumbnail_count). Returns a per-service breakdown plus total_usd."""
        locals_ = locals()
        payload: dict = {"feature": feature}
        for k in _ESTIMATE_FIELDS:
            v = locals_[k]
            if v is not None:
                payload[k] = v
        return await agent_tools.estimate_cost(invite_code, payload)

    async def get_job_cost(feature: str, record_id: str):
        """Return the per-service cost breakdown for an existing job, plus
        total and pricing confidence (high/medium/low with notes for any
        estimated fields)."""
        return await agent_tools.get_job_cost(invite_code, feature, record_id)

    async def list_recent_jobs(feature: str, limit: int = 5):
        """List the most recent records for any feature, sorted newest-first.
        Returns [{id, name, status, createdAt}]. Use this FIRST to resolve
        relative references like 'my last production' before calling
        get_job_cost. `feature` is one of
        production/adapts/reframe/promo/key_moments/thumbnails."""
        return await agent_tools.list_recent_jobs(invite_code, feature, limit)

    return [
        get_pricing_rates,
        get_feature_services,
        estimate_cost,
        get_job_cost,
        list_recent_jobs,
    ]


def create_orchestrator(invite_code: str):
    """The central Router agent that delegates to specialists and handles pricing itself."""
    reset_agent_context()
    model = create_model()
    return LlmAgent(
        name="Aanya",
        model=model,
        instruction=f"{STRICT_SCOPE_INSTRUCTION}\n{_ORCHESTRATOR_ROLE}",
        tools=[FunctionTool(func=f) for f in _make_orchestrator_tools(invite_code)],
        sub_agents=[
            create_director_agent(invite_code, model),
            create_editor_agent(invite_code, model),
            create_marketer_agent(invite_code, model),
        ],
    )

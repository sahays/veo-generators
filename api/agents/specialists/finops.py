"""FinOps, Models & Asset Inventory specialist (`finops_agent`) — pricing, cost estimates, job usage breakdowns, AI models, and uploads."""

from typing import Any, Callable, Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import build_specialist

_FINOPS_ROLE = (
    "You are the FinOps, Pricing & Platform Inventory Specialist (`finops_agent`). "
    "You handle all pricing rates, service consumption maps, token consumption / usage metrics, "
    "pre-execution cost estimates, post-job cost breakdowns, active AI models/regions, and uploaded media inventory.\n"
    "Note: 'Orientations' in the UI corresponds to feature='reframe'.\n"
    "For cost or token consumption questions:\n"
    "- Never transfer or delegate back to a feature agent for token/cost questions — you own all usage and cost data.\n"
    "- If the user references a specific record ID, call get_job_cost(feature, id) directly.\n"
    "- If the user says 'last/previous/most recent X' or 'my X' without an ID, "
    "first call list_recent_jobs(feature, limit=1) to resolve the ID (and inspect its `usage` field for input_tokens/output_tokens), "
    "then call get_job_cost(feature, id) for the full service and USD breakdown. Do NOT ask the user for an ID — look it up yourself.\n"
    "- If the user asks to list or compare multiple recent jobs, call "
    "list_recent_jobs, then get_job_cost for each, and present a GFM markdown table.\n"
    "- If the user asks 'how much would X cost' before running a job, use estimate_cost.\n"
    "- If the user asks about rates or which services are billed, use "
    "get_pricing_rates or get_feature_services.\n"
    "- Always surface the pricing_confidence field when you return a job cost — "
    "say 'this is approximate' when it's not 'high'."
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


def _make_estimate_cost_tool(invite_code: str) -> Callable:
    async def estimate_cost(
        feature: str,
        scene_count: Optional[int] = None,
        video_length_seconds: Optional[float] = None,
        variant_count: Optional[int] = None,
        source_duration_seconds: Optional[float] = None,
        segment_count: Optional[int] = None,
        has_title_card: Optional[bool] = None,
        thumbnail_count: Optional[int] = None,
    ) -> Any:
        """Estimate the cost of a job BEFORE it runs."""
        locals_ = locals()
        payload = {
            "feature": feature,
            **{k: locals_[k] for k in _ESTIMATE_FIELDS if locals_[k] is not None},
        }
        return await agent_tools.estimate_cost(invite_code, payload)

    return estimate_cost


def make_finops_tools(invite_code: str) -> list:
    async def get_pricing_rates() -> Any:
        """Return the current pricing catalog."""
        return await agent_tools.get_pricing_rates(invite_code)

    async def get_feature_services() -> Any:
        """Return the list of services each feature consumes with rates inlined."""
        return await agent_tools.get_feature_services(invite_code)

    async def get_job_cost(feature: str, record_id: str) -> Any:
        """Return the per-service cost breakdown for an existing job."""
        return await agent_tools.get_job_cost(invite_code, feature, record_id)

    async def list_recent_jobs(feature: str, limit: int = 5) -> Any:
        """List the most recent records for any feature, sorted newest-first."""
        return await agent_tools.list_recent_jobs(invite_code, feature, limit)

    async def list_registered_models() -> Any:
        """List active AI models (text, image, video) and their supported regions."""
        return await agent_tools.list_ai_models(invite_code)

    async def list_uploaded_assets(
        file_type: Optional[str] = None, limit: int = 10
    ) -> Any:
        """List uploaded media files ('video' or 'image')."""
        return await agent_tools.list_uploads(invite_code, file_type, limit)

    return [
        get_pricing_rates,
        get_feature_services,
        _make_estimate_cost_tool(invite_code),
        get_job_cost,
        list_recent_jobs,
        list_registered_models,
        list_uploaded_assets,
    ]


def create_finops_agent(invite_code: str, model: Optional[Gemini] = None) -> LlmAgent:
    return build_specialist(
        "finops_agent",
        _FINOPS_ROLE,
        make_finops_tools(invite_code),
        model=model,
        tier="finops",
    )

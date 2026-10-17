"""Productions & Prompts specialist (`productions_agent`) — manages video productions, lifecycle steps, and system prompts."""

from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini

from .. import tools as agent_tools
from .._shared import (
    _request_context,
    build_specialist,
    make_check_job_status,
    propose_job,
    resolve_prompt_name,
)

_PRODUCTIONS_ROLE = (
    "You are the Productions & Script Studio Specialist (`productions_agent`). "
    "You manage multi-scene video productions, scripts, storyboards, and system prompt templates.\n"
    "IMPORTANT: Call list_prompt_categories() to discover categories (with example "
    "prompt names), then match the user's intent to the best-fitting category and "
    "call list_prompts(category) with the exact ID. Never ask the user to choose "
    "from raw category IDs — infer the best match from the examples and proceed.\n"
    "IMPORTANT: Use propose_production() to create an A2UI confirmation card. "
    "Never execute new production jobs directly — always let the user review and confirm first.\n"
    "For existing productions, you can trigger lifecycle stages (analyze script, "
    "generate-storyboard, generate-videos, stitch) via advance_production_stage()."
)

_ALLOWED_PRODUCTION_STAGES = {
    "run",
    "approve-G1",
    "approve-G2",
    "approve-G3",
    "S1_EXTRACT",
    "S2_SCREENPLAY",
    "S3_DESIGN",
    "S4_SHOTS",
    "S5_MUSIC",
    "S6_VALIDATE",
    "S7_COMPILE",
    "S8_RENDER",
    "S9_QA",
    "S10_ASSEMBLE",
    "analyze",
    "review",
    "render",
    "render-draft",
    "upgrade-final",
    "evaluate",
    "regenerate-flagged",
    "generate-storyboard",
    "generate-videos",
    "stitch",
}


async def _format_prompt_categories(invite_code: str) -> str:
    cats = await agent_tools.list_prompt_categories(invite_code)
    if not isinstance(cats, list) or not cats:
        return "No prompt categories found."
    lines = [
        f"- {c['id']} ({c['count']} prompts) e.g. {', '.join(c.get('examples', []))}"
        for c in cats
    ]
    return "Available prompt categories:\n" + "\n".join(lines)


async def _format_prompts(invite_code: str, category: str) -> str:
    prompts = await agent_tools.list_system_prompts(invite_code, category)
    _request_context.get().update({"prompt_picker": category})
    if not isinstance(prompts, list) or not prompts:
        return f"No prompts found for '{category}'."
    lines = [
        f"- {p.get('name', 'Unnamed')} (ID: {p.get('id', '?')}): {p.get('description', '')}"
        for p in prompts
    ]
    return f"Prompts for '{category}':\n" + "\n".join(lines)


async def _do_propose_production(
    invite_code: str,
    name: str,
    base_concept: str,
    prompt_id: Optional[str],
    video_length: str,
    orientation: str,
    project_type: str,
    language: str,
) -> str:
    resolved: dict = {}
    if prompt_id:
        resolved["prompt_name"] = await resolve_prompt_name(invite_code, prompt_id)
    clean_len = str(video_length).rstrip("s").strip() or "16"
    params: dict = {
        "name": name,
        "base_concept": base_concept,
        "video_length": clean_len,
        "orientation": orientation,
        "type": project_type,
        "language": language,
    }
    if prompt_id:
        params["prompt_id"] = prompt_id
    return propose_job("production", f"Create production: {name}", params, resolved)


def _make_propose_production_tool(invite_code: str) -> Any:
    async def propose_production(
        name: str,
        base_concept: str,
        prompt_id: Optional[str] = None,
        video_length: str = "16",
        orientation: str = "16:9",
        project_type: str = "movie",
        language: str = "en-IN",
    ) -> str:
        """Propose creating a new video production (`video_length` in seconds e.g. '16', '24', '32', '48'; `language` in 'en-IN', 'hi-IN', 'en-US'; `project_type` in 'movie', 'advertizement', 'social'). Returns an interactive A2UI confirmation card."""
        return await _do_propose_production(
            invite_code,
            name,
            base_concept,
            prompt_id,
            video_length,
            orientation,
            project_type,
            language,
        )

    return propose_production


def _make_director_tools(invite_code: str) -> list:
    async def list_recent_productions(limit: int = 5) -> Any:
        """List the most recent video production projects."""
        return await agent_tools.list_recent_productions(invite_code, limit)

    async def list_prompt_categories() -> str:
        """Discover prompt categories. Call this FIRST, match user intent to a category ID, then call list_prompts(category) with the exact ID."""
        return await _format_prompt_categories(invite_code)

    async def list_prompts(category: str) -> str:
        """List system prompts for a category ID."""
        return await _format_prompts(invite_code, category)

    async def advance_production_stage(production_id: str, stage: str) -> Any:
        """Trigger a lifecycle stage or StoryGraph gate approval on an existing production."""
        if stage not in _ALLOWED_PRODUCTION_STAGES:
            return f"Invalid stage '{stage}'. Valid stages: {', '.join(sorted(_ALLOWED_PRODUCTION_STAGES))}"
        return await agent_tools.trigger_production_step(
            invite_code, production_id, stage
        )

    return [
        list_recent_productions,
        _make_propose_production_tool(invite_code),
        advance_production_stage,
        list_prompt_categories,
        list_prompts,
        make_check_job_status(invite_code),
    ]


def create_productions_agent(invite_code: str, model: Gemini | None = None) -> LlmAgent:
    return build_specialist(
        "productions_agent",
        _PRODUCTIONS_ROLE,
        _make_director_tools(invite_code),
        model=model,
        tier="creative",
    )


def create_director_agent(invite_code: str, model: Gemini | None = None) -> LlmAgent:
    return create_productions_agent(invite_code, model)

"""Director specialist — manages video projects and system-prompt browsing."""

from typing import Optional

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

_DIRECTOR_ROLE = (
    "You are the Production Director. You manage video projects and scripts.\n"
    "IMPORTANT: Call list_prompt_categories() to discover categories (with example "
    "prompt names), then match the user's intent to the best-fitting category and "
    "call list_prompts(category) with the exact ID. Never ask the user to choose "
    "from raw category IDs — infer the best match from the examples and proceed.\n"
    "IMPORTANT: Use propose_production() to create a confirmation card. "
    "Never execute jobs directly — always let the user review and confirm first."
)


def _make_director_tools(invite_code: str) -> list:
    async def list_recent_productions(limit: int = 5):
        """List the most recent video production projects."""
        return await agent_tools.list_recent_productions(invite_code, limit)

    async def list_prompt_categories():
        """Discover prompt categories. Call this FIRST, match user intent to a
        category ID, then call list_prompts(category) with the exact ID."""
        cats = await agent_tools.list_prompt_categories(invite_code)
        if not isinstance(cats, list) or not cats:
            return "No prompt categories found."
        lines = [
            f"- {c['id']} ({c['count']} prompts) e.g. {', '.join(c.get('examples', []))}"
            for c in cats
        ]
        return "Available prompt categories:\n" + "\n".join(lines)

    async def list_prompts(category: str):
        """List system prompts for a category ID."""
        prompts = await agent_tools.list_system_prompts(invite_code, category)
        _request_context.get().update({"prompt_picker": category})
        if not isinstance(prompts, list) or not prompts:
            return f"No prompts found for '{category}'."
        lines = [
            f"- {p.get('name', 'Unnamed')} (ID: {p.get('id', '?')}): "
            f"{p.get('description', '')}"
            for p in prompts
        ]
        return f"Prompts for '{category}':\n" + "\n".join(lines)

    async def propose_production(
        name: str, base_concept: str, prompt_id: Optional[str] = None
    ):
        """Propose creating a new video production. Returns a confirmation card."""
        resolved: dict = {}
        if prompt_id:
            resolved["prompt_name"] = await resolve_prompt_name(invite_code, prompt_id)
        params: dict = {"name": name, "base_concept": base_concept}
        if prompt_id:
            params["prompt_id"] = prompt_id
        return propose_job("production", f"Create production: {name}", params, resolved)

    return [
        list_recent_productions,
        propose_production,
        list_prompt_categories,
        list_prompts,
        make_check_job_status(invite_code),
    ]


def create_director_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return build_specialist(
        "director", _DIRECTOR_ROLE, _make_director_tools(invite_code), model
    )

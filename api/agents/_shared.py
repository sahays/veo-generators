"""Shared scaffolding for the orchestrator + specialists.

Lives outside `factory.py` so each specialist module can import these
helpers without forming a cycle with the orchestrator.
"""

import contextvars
import logging
import os
from typing import List, Optional

from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools import FunctionTool

from . import tools as agent_tools

logger = logging.getLogger(__name__)

AGENT_MODEL_ID = os.getenv("GEMINI_AGENT_ORCHESTRATOR", "gemini-3.1-flash-lite-preview")

# Request-scoped context so concurrent requests don't clobber each other.
_request_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_request_context", default={}
)

STRICT_SCOPE_INSTRUCTION = (
    "SCOPE POLICY: You are an AI assistant for the Veo Generators application. "
    "You handle video production, scripts, orientations, thumbnails, social media adapts, "
    "promos, costs, usage, and all features of this app.\n"
    "DO NOT answer questions completely unrelated to this app (general knowledge, jokes, "
    "coding help for other projects, politics, news). For those, politely decline.\n"
    "IMPORTANT: If a question relates to this app but you lack the tools or data to answer it, "
    "say so honestly (e.g. 'I don't have access to cost breakdowns yet') — do NOT "
    "reject it as out of scope. Questions about job details, pricing, usage, and how the app "
    "works are always in scope even if you can't fully answer them."
)


def create_model() -> Gemini:
    """Create a Gemini model with explicit Vertex AI credentials (matching GeminiService)."""
    model = Gemini(model=AGENT_MODEL_ID)
    model.__dict__["api_client"] = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GEMINI_REGION", "global"),
    )
    return model


def propose_job(job_type: str, title: str, params: dict, resolved: dict) -> str:
    """Record a job proposal in request-scoped context for frontend confirmation."""
    _request_context.get()["confirmation"] = {
        "job_type": job_type,
        "title": title,
        "params": params,
        "resolved": resolved,
    }
    return (
        f"I've prepared your {job_type.replace('_', ' ')} proposal. "
        "Please review the details and click Confirm when ready."
    )


def get_agent_context() -> dict:
    """Accumulated context (confirmations, source pickers, etc.) from the
    current request."""
    return _request_context.get()


def reset_agent_context() -> None:
    """Called by `create_orchestrator` at the start of each request."""
    _request_context.set({})


def display_name(source_filename: str, gcs_uri: str) -> str:
    return source_filename or gcs_uri.rsplit("/", 1)[-1]


async def resolve_prompt_name(invite_code: str, prompt_id: str) -> str:
    """Look up a prompt's display name by ID. Returns '' if not found."""
    if not prompt_id:
        return ""
    prompts = await agent_tools.list_system_prompts(invite_code, category=None)
    if not isinstance(prompts, list):
        return ""
    by_id = {p.get("id"): p for p in prompts}
    match = by_id.get(prompt_id)
    return match.get("name", "") if match else ""


def build_specialist(
    name: str, role_instruction: str, tool_funcs: list, model: Gemini
) -> LlmAgent:
    """Assemble an LlmAgent from a role-specific instruction and tool functions."""
    return LlmAgent(
        name=name,
        model=model,
        instruction=f"{STRICT_SCOPE_INSTRUCTION}\n{role_instruction}",
        tools=[FunctionTool(func=f) for f in tool_funcs],
    )


def make_check_job_status(invite_code: str):
    async def check_job_status(job_type: str, job_id: str):
        """Check the status of a specific job."""
        return str(await agent_tools.get_job_status(invite_code, job_type, job_id))

    return check_job_status


def make_list_available_videos(_invite_code: str):
    async def list_available_videos():
        """Show available video sources."""
        _request_context.get().update({"source_picker": True})
        return "I've opened the video selector for you."

    return list_available_videos


__all__ = [
    "AGENT_MODEL_ID",
    "List",
    "Optional",
    "STRICT_SCOPE_INSTRUCTION",
    "build_specialist",
    "create_model",
    "display_name",
    "get_agent_context",
    "make_check_job_status",
    "make_list_available_videos",
    "propose_job",
    "reset_agent_context",
    "resolve_prompt_name",
    "_request_context",
]

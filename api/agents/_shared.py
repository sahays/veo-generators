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
from .tools._client import api_call

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


def make_prompt_lister(invite_code: str, category: str, tool_name: str, label: str):
    """Build a tool that lists prompts for a fixed category and opens the picker.

    Mirrors the director's inline `list_prompts` pattern so specialists that
    need a prompt for a specific feature (key moments, thumbnails) can surface
    the `PromptPicker` widget without the user knowing a prompt ID.
    """

    async def lister():
        prompts = await agent_tools.list_system_prompts(invite_code, category)
        # Setting prompt_picker in the request context tells the frontend to
        # render PromptPicker(category) so the user can click a prompt.
        _request_context.get().update({"prompt_picker": category})
        if not isinstance(prompts, list) or not prompts:
            return f"No {label} prompts found."
        lines = [
            f"- {p.get('name', 'Unnamed')} (ID: {p.get('id', '?')}): "
            f"{p.get('description', '')}"
            for p in prompts
        ]
        return f"{label} prompts:\n" + "\n".join(lines)

    lister.__name__ = tool_name  # FunctionTool derives the tool name from __name__
    lister.__doc__ = (
        f"List {label} prompts and open a picker for the user to choose one."
    )
    return lister


def _match_source(items, needle: str) -> Optional[str]:
    """Return the gs:// URI of the item whose id/name/filename matches needle."""
    if not isinstance(items, list):
        return None
    for it in items:
        names = {
            str(it.get("id", "")).lower(),
            str(it.get("name", "")).lower(),
            str(it.get("display_name", "")).lower(),
            str(it.get("filename", "")).lower(),
        }
        uri = it.get("gcs_uri") or it.get("final_video_url")
        if needle in names and uri and uri.startswith("gs://"):
            return uri
    return None


async def resolve_source_uri(
    invite_code: str, ref: str, kind: str = "video"
) -> Optional[str]:
    """Resolve a user-supplied source reference to a gs:// URI.

    Accepts a gs:// URI (returned as-is) or an id/name/filename. The agent
    sometimes passes a production ID (e.g. 'p-...') or a display name instead of
    the underlying URI; resolving it here stops a bad `file_uri`/source from
    reaching the model or worker. `kind` selects which catalog to search:
    "video" → productions + video uploads; "image" → adapt image uploads.
    Returns None when nothing matches so the caller can open the source picker.
    """
    if not ref:
        return None
    if ref.startswith("gs://"):
        return ref
    needle = ref.strip().lower()

    if kind == "image":
        imgs = await api_call("GET", "/api/v1/adapts/sources/uploads", invite_code)
        return _match_source(imgs, needle)

    prods = await api_call("GET", "/api/v1/thumbnails/sources/productions", invite_code)
    match = _match_source(prods, needle)
    if match:
        return match
    ups = await api_call("GET", "/api/v1/promo/sources/uploads", invite_code)
    return _match_source(ups, needle)


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


def make_list_available_images(_invite_code: str):
    async def list_available_images():
        """Show available image sources (for adapts, which resize an image)."""
        _request_context.get().update({"source_picker": "image"})
        return "I've opened the image selector for you."

    return list_available_images


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
    "make_list_available_images",
    "make_list_available_videos",
    "make_prompt_lister",
    "propose_job",
    "reset_agent_context",
    "resolve_prompt_name",
    "resolve_source_uri",
    "_request_context",
]

"""Shared scaffolding for the orchestrator + 8 feature specialists.

Lives outside `factory.py` so each specialist module can import these
helpers without forming a cycle with the orchestrator.
"""

import contextvars
import logging
import os
import re
from typing import Any, Dict, List, Optional

from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.tools import FunctionTool

from . import tools as agent_tools
from .tools._client import api_call

logger = logging.getLogger(__name__)

AGENT_MODEL_ID = os.getenv("GEMINI_AGENT_ORCHESTRATOR", "gemini-3.5-flash-lite")

MODEL_TIER_ENV = {
    "router": ("GEMINI_AGENT_ORCHESTRATOR", "gemini-3.5-flash-lite"),
    "finops": ("GEMINI_AGENT_FINOPS_MODEL", "gemini-3.5-flash-lite"),
    "specialist": ("GEMINI_AGENT_SPECIALIST_MODEL", "gemini-3.8-flash"),
    "creative": ("GEMINI_AGENT_CREATIVE_MODEL", "gemini-3.8-flash"),
}

# Request-scoped context so concurrent requests don't clobber each other.
_request_context: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_request_context", default={}
)

STRICT_SCOPE_INSTRUCTION = (
    "SCOPE POLICY: You are an AI assistant for the Veo Generators application. "
    "You handle video production, scripts, orientations/reframing, thumbnails, "
    "key moments, social media adapts, promos, multi-language dubbing, "
    "costs, usage, and all features of this app.\n"
    "DO NOT answer questions completely unrelated to this app (general knowledge, jokes, "
    "coding help for other projects, politics, news). For those, politely decline.\n"
    "IMPORTANT: If a question relates to this app but you lack the tools or data to answer it, "
    "say so honestly — do NOT reject it as out of scope. Questions about job details, pricing, "
    "usage, and how the app works are always in scope.\n"
    "FORMATTING POLICY: Always format your responses in clean GitHub-Flavored Markdown (GFM). "
    "NEVER output raw HTML tags such as <br>, <br/>, <p>, <ul>, <li>, or <b>. "
    "Inside Markdown table cells, NEVER use <br> or bullet characters (•); either put one service/item "
    "per table row or separate multiple items in a cell with '; '."
)


def sanitize_markdown_response(text: str) -> str:
    """Strip raw HTML line breaks (<br>) from LLM output so GFM tables and lists render cleanly."""
    if not text or "<br" not in text.lower():
        return text
    cleaned_lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            line = re.sub(r"<br\s*/?>\s*[•*\-]?\s*", "; ", line, flags=re.IGNORECASE)
            line = re.sub(r"\|\s*•\s*", "| ", line)
        else:
            line = re.sub(r"<br\s*/?>", "\n", line, flags=re.IGNORECASE)
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def resolve_tier_model_id(tier: str = "router") -> str:
    """Return the model ID configured for a given agent responsibility tier."""
    env_var, default_model = MODEL_TIER_ENV.get(tier, MODEL_TIER_ENV["specialist"])
    return os.getenv(env_var, default_model)


def create_model(tier: str = "router") -> Gemini:
    """Create a Gemini model with explicit Vertex AI credentials for the given responsibility tier."""
    model_id = resolve_tier_model_id(tier)
    model = Gemini(model=model_id)
    model.__dict__["api_client"] = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GEMINI_REGION", "global"),
    )
    return model


def propose_job(
    job_type: str,
    title: str,
    params: dict,
    resolved: dict,
    missing_fields: Optional[List[str]] = None,
    options: Optional[Dict[str, Any]] = None,
) -> str:
    """Record a job proposal + A2UI widget envelope in request-scoped context."""
    ctx = _request_context.get()
    proposal = {
        "job_type": job_type,
        "title": title,
        "params": params,
        "resolved": resolved,
    }
    ctx["confirmation"] = proposal
    ctx["a2ui"] = {
        "kind": "job_proposal",
        **proposal,
        "missing_fields": missing_fields or [],
        "options": options or {},
    }
    return (
        f"I've prepared your {job_type.replace('_', ' ')} proposal. "
        "Please review the interactive card and click Confirm when ready."
    )


def get_agent_context() -> dict:
    """Accumulated context (confirmations, A2UI payloads, source pickers) from the current request."""
    return _request_context.get()


def reset_agent_context() -> None:
    """Called by `create_orchestrator` at the start of each request."""
    _request_context.set({})


def display_name(source_filename: str, gcs_uri: str) -> str:
    return source_filename or (
        gcs_uri.rsplit("/", 1)[-1] if gcs_uri else "Select source"
    )


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
    name: str,
    role_instruction: str,
    tool_funcs: list,
    model: Optional[Gemini] = None,
    tier: str = "specialist",
) -> LlmAgent:
    """Assemble an LlmAgent from a role-specific instruction and tool functions."""
    active_model = model or create_model(tier)
    return LlmAgent(
        name=name,
        model=active_model,
        instruction=f"{STRICT_SCOPE_INSTRUCTION}\n{role_instruction}",
        tools=[FunctionTool(func=f) for f in tool_funcs],
    )


def make_prompt_lister(invite_code: str, category: str, tool_name: str, label: str):
    """Build a tool that lists prompts for a fixed category and opens the picker."""

    async def lister():
        prompts = await agent_tools.list_system_prompts(invite_code, category)
        _request_context.get().update({"prompt_picker": category})
        if not isinstance(prompts, list) or not prompts:
            return f"No {label} prompts found."
        lines = [
            f"- {p.get('name', 'Unnamed')} (ID: {p.get('id', '?')}): "
            f"{p.get('description', '')}"
            for p in prompts
        ]
        return f"{label} prompts:\n" + "\n".join(lines)

    lister.__name__ = tool_name
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
    """Resolve a user-supplied source reference to a gs:// URI."""
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


def source_picker_fallback(kind: str = "video") -> str:
    noun = "images" if kind == "image" else "videos"
    selector = "image" if kind == "image" else "video"
    return (
        f"I couldn't match that to one of your {noun}. I've opened the "
        f"{selector} selector — pick the source and I'll continue."
    )


async def resolve_or_pick(
    invite_code: str, gcs_uri: str, kind: str = "video"
) -> Optional[str]:
    """Resolve a source reference to a gs:// URI, or open the picker and return None."""
    resolved = await resolve_source_uri(invite_code, gcs_uri, kind=kind)
    if not resolved:
        _request_context.get().update(
            {"source_picker": "image" if kind == "image" else True}
        )
    return resolved


def make_prompt_video_proposer(
    invite_code: str, job_type: str, title: str, func_name: str, doc: str
):
    """Build a propose_* tool for video+prompt analysis features (key_moments, thumbnails)."""

    async def proposer(gcs_uri: str, prompt_id: str, source_filename: str = "") -> str:
        resolved_uri = await resolve_or_pick(invite_code, gcs_uri, kind="video")
        if not resolved_uri:
            return source_picker_fallback("video")
        return propose_job(
            job_type,
            title,
            {
                "gcs_uri": resolved_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            {
                "prompt_name": await resolve_prompt_name(invite_code, prompt_id),
                "source_name": display_name(source_filename, resolved_uri),
            },
        )

    proposer.__name__ = func_name
    proposer.__doc__ = doc
    return proposer


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
    "MODEL_TIER_ENV",
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
    "make_prompt_video_proposer",
    "propose_job",
    "reset_agent_context",
    "resolve_or_pick",
    "resolve_prompt_name",
    "resolve_source_uri",
    "resolve_tier_model_id",
    "source_picker_fallback",
    "_request_context",
]

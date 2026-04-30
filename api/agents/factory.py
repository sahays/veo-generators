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


def _create_model() -> Gemini:
    """Create a Gemini model with explicit Vertex AI credentials (matching GeminiService)."""
    model = Gemini(model=AGENT_MODEL_ID)
    model.__dict__["api_client"] = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GEMINI_REGION", "global"),
    )
    return model


def _propose_job(job_type: str, title: str, params: dict, resolved: dict) -> str:
    """Record a job proposal in request-scoped context for frontend confirmation."""
    ctx = _request_context.get()
    ctx["confirmation"] = {
        "job_type": job_type,
        "title": title,
        "params": params,
        "resolved": resolved,
    }
    return (
        f"I've prepared your {job_type.replace('_', ' ')} proposal. "
        "Please review the details and click Confirm when ready."
    )


# ── Shared utilities ─────────────────────────────────────────────────


def _display_name(source_filename: str, gcs_uri: str) -> str:
    return source_filename or gcs_uri.rsplit("/", 1)[-1]


async def _resolve_prompt_name(invite_code: str, prompt_id: str) -> str:
    """Look up a prompt's display name by ID. Returns '' if not found."""
    if not prompt_id:
        return ""
    prompts = await agent_tools.list_system_prompts(invite_code, category=None)
    if not isinstance(prompts, list):
        return ""
    match = next((p for p in prompts if p.get("id") == prompt_id), None)
    return match.get("name", "") if match else ""


def _build_specialist(
    name: str, role_instruction: str, tool_funcs: list, model: Gemini
) -> LlmAgent:
    """Assemble an LlmAgent from a role-specific instruction and tool functions."""
    return LlmAgent(
        name=name,
        model=model,
        instruction=f"{STRICT_SCOPE_INSTRUCTION}\n{role_instruction}",
        tools=[FunctionTool(func=f) for f in tool_funcs],
    )


def _make_check_job_status(invite_code: str):
    async def check_job_status(job_type: str, job_id: str):
        """Check the status of a specific job."""
        return str(await agent_tools.get_job_status(invite_code, job_type, job_id))

    return check_job_status


def _make_list_available_videos(_invite_code: str):
    async def list_available_videos():
        """Show available video sources."""
        _request_context.get().update({"source_picker": True})
        return "I've opened the video selector for you."

    return list_available_videos


# ── Director tool builders ───────────────────────────────────────────


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
            resolved["prompt_name"] = await _resolve_prompt_name(invite_code, prompt_id)
        params: dict = {"name": name, "base_concept": base_concept}
        if prompt_id:
            params["prompt_id"] = prompt_id
        return _propose_job(
            "production", f"Create production: {name}", params, resolved
        )

    return [
        list_recent_productions,
        propose_production,
        list_prompt_categories,
        list_prompts,
        _make_check_job_status(invite_code),
    ]


# ── Editor tool builders ─────────────────────────────────────────────


def _make_editor_tools(invite_code: str) -> list:
    async def list_recent_reframes(limit: int = 5):
        """List the most recent video reframe jobs."""
        return await agent_tools.list_recent_reframes(invite_code, limit)

    async def list_recent_key_moments(limit: int = 5):
        """List the most recent key moments analysis jobs."""
        return await agent_tools.list_recent_key_moments(invite_code, limit)

    async def list_recent_thumbnails(limit: int = 5):
        """List the most recent thumbnail jobs."""
        return await agent_tools.list_recent_thumbnails(invite_code, limit)

    async def list_content_types():
        """List valid content types for reframing. Call before proposing a reframe."""
        types = await agent_tools.list_content_types(invite_code)
        if not isinstance(types, list) or not types:
            return "No content types found."
        lines = [
            f"- {t['id']}: {t.get('description', '')} (strategy: {t.get('cv_strategy', '')})"
            for t in types
        ]
        return "Available content types:\n" + "\n".join(lines)

    async def propose_reframe(
        gcs_uri: str, content_type: str = "other", source_filename: str = ""
    ):
        """Propose a reframe. Returns a confirmation card."""
        valid = await agent_tools.list_content_types(invite_code)
        valid_ids = [t["id"] for t in valid] if isinstance(valid, list) else []
        if valid_ids and content_type not in valid_ids:
            return (
                f"Invalid content_type '{content_type}'. "
                f"Valid options: {', '.join(valid_ids)}"
            )
        label = (
            next(
                (
                    t.get("description", t["id"])
                    for t in valid
                    if t["id"] == content_type
                ),
                content_type,
            )
            if isinstance(valid, list)
            else content_type
        )
        return _propose_job(
            "reframe",
            "Reframe video to vertical",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "content_type": content_type,
                "blurred_bg": False,
                "vertical_split": False,
            },
            {
                "source_name": _display_name(source_filename, gcs_uri),
                "content_type_label": label,
            },
        )

    async def propose_key_moments(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose a Key Moments analysis. Returns a confirmation card."""
        return _propose_job(
            "key_moments",
            "Analyze key moments",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            {
                "prompt_name": await _resolve_prompt_name(invite_code, prompt_id),
                "source_name": _display_name(source_filename, gcs_uri),
            },
        )

    async def propose_thumbnails(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose thumbnail generation/analysis. Returns a confirmation card."""
        return _propose_job(
            "thumbnails",
            "Generate thumbnails",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            {
                "prompt_name": await _resolve_prompt_name(invite_code, prompt_id),
                "source_name": _display_name(source_filename, gcs_uri),
            },
        )

    return [
        list_recent_reframes,
        list_recent_key_moments,
        list_recent_thumbnails,
        list_content_types,
        propose_reframe,
        propose_key_moments,
        propose_thumbnails,
        _make_list_available_videos(invite_code),
        _make_check_job_status(invite_code),
    ]


# ── Marketer tool builders ───────────────────────────────────────────


def _make_marketer_tools(invite_code: str) -> list:
    async def list_recent_promos(limit: int = 5):
        """List the most recent promotional video jobs."""
        return await agent_tools.list_recent_promos(invite_code, limit)

    async def list_recent_adapts(limit: int = 5):
        """List the most recent social media adaptation jobs."""
        return await agent_tools.list_recent_adapts(invite_code, limit)

    async def list_adapt_options():
        """List valid aspect ratios and preset bundles for adapt jobs."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        if not isinstance(data, dict):
            return "Could not fetch adapt options."
        lines: list[str] = []
        bundles = data.get("preset_bundles", {})
        if bundles:
            lines.append("Preset bundles:")
            for k, v in bundles.items():
                lines.append(f"  - {k} ({v['name']}): {', '.join(v['ratios'])}")
        ratios = data.get("ratios", [])
        if ratios:
            lines.append(f"All valid ratios: {', '.join(ratios)}")
        return "\n".join(lines)

    async def propose_promo(
        gcs_uri: str,
        target_duration: int = 60,
        source_filename: str = "",
        text_overlay: bool = False,
    ):
        """Propose a new promo. Returns a confirmation card."""
        return _propose_job(
            "promo",
            f"Create {target_duration // 60}-min promo",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "target_duration": target_duration,
                "text_overlay": text_overlay,
                "generate_thumbnail": False,
            },
            {"source_name": _display_name(source_filename, gcs_uri)},
        )

    async def propose_adapts(
        gcs_uri: str, aspect_ratios: List[str], source_filename: str = ""
    ):
        """Propose adapting a video for multiple platforms. Returns a confirmation card."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        valid = data.get("ratios", []) if isinstance(data, dict) else []
        if valid:
            invalid = [r for r in aspect_ratios if r not in valid]
            if invalid:
                return (
                    f"Invalid aspect ratios: {', '.join(invalid)}. "
                    f"Valid options: {', '.join(valid)}"
                )
        return _propose_job(
            "adapts",
            f"Adapt for {len(aspect_ratios)} platforms",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "aspect_ratios": aspect_ratios,
            },
            {"source_name": _display_name(source_filename, gcs_uri)},
        )

    return [
        list_recent_promos,
        list_recent_adapts,
        list_adapt_options,
        propose_promo,
        propose_adapts,
        _make_list_available_videos(invite_code),
        _make_check_job_status(invite_code),
    ]


# ── Agent factories (thin) ───────────────────────────────────────────


_DIRECTOR_ROLE = (
    "You are the Production Director. You manage video projects and scripts.\n"
    "IMPORTANT: Call list_prompt_categories() to discover categories (with example "
    "prompt names), then match the user's intent to the best-fitting category and "
    "call list_prompts(category) with the exact ID. Never ask the user to choose "
    "from raw category IDs — infer the best match from the examples and proceed.\n"
    "IMPORTANT: Use propose_production() to create a confirmation card. "
    "Never execute jobs directly — always let the user review and confirm first."
)

_EDITOR_ROLE = (
    "You are the Video Editor. You process existing videos (reframe, key moments, thumbnails).\n"
    "IMPORTANT: Call list_content_types() before reframing to pick the correct content type.\n"
    "IMPORTANT: Use propose_* tools to create confirmation cards. "
    "Never execute jobs directly — always let the user review and confirm first."
)

_MARKETER_ROLE = (
    "You are the Marketing Expert. You create promos and social adaptations.\n"
    "IMPORTANT: Call list_adapt_options() before creating adapts to show the user "
    "valid aspect ratios and preset bundles.\n"
    "IMPORTANT: Use propose_* tools to create confirmation cards. "
    "Never execute jobs directly — always let the user review and confirm first."
)


def create_director_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return _build_specialist(
        "director", _DIRECTOR_ROLE, _make_director_tools(invite_code), model
    )


def create_editor_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return _build_specialist(
        "editor", _EDITOR_ROLE, _make_editor_tools(invite_code), model
    )


def create_marketer_agent(invite_code: str, model: Gemini) -> LlmAgent:
    return _build_specialist(
        "marketer", _MARKETER_ROLE, _make_marketer_tools(invite_code), model
    )


# ── Orchestrator tool builders ───────────────────────────────────────


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
        payload: dict = {"feature": feature}
        for k, v in {
            "scene_count": scene_count,
            "video_length_seconds": video_length_seconds,
            "variant_count": variant_count,
            "source_duration_seconds": source_duration_seconds,
            "segment_count": segment_count,
            "has_title_card": has_title_card,
            "thumbnail_count": thumbnail_count,
        }.items():
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
    _request_context.set({})
    model = _create_model()
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


def get_agent_context() -> dict:
    """Returns the accumulated context from the current request."""
    return _request_context.get()

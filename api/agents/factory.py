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


# ── Shared tool functions (used by multiple agents) ─────────────────


def _make_check_job_status(invite_code: str):
    async def check_job_status(job_type: str, job_id: str):
        """Check the status of a specific job."""
        return str(await agent_tools.get_job_status(invite_code, job_type, job_id))

    return check_job_status


def _make_list_available_videos(invite_code: str):
    async def list_available_videos():
        """Show available video sources."""
        _request_context.get().update({"source_picker": True})
        return "I've opened the video selector for you."

    return list_available_videos


# ── Agent builders ───────────────────────────────────────────────────


def create_director_agent(invite_code: str, model: Gemini) -> LlmAgent:
    async def list_recent_productions(limit: int = 5):
        """List the most recent video production projects."""
        return await agent_tools.list_recent_productions(invite_code, limit)

    async def propose_production(
        name: str, base_concept: str, prompt_id: Optional[str] = None
    ):
        """Propose creating a new video production. Does NOT execute — returns a confirmation card for the user to review."""
        resolved: dict = {}
        if prompt_id:
            prompts = await agent_tools.list_system_prompts(invite_code, category=None)
            valid_ids = (
                {p.get("id") for p in prompts} if isinstance(prompts, list) else set()
            )
            if valid_ids and prompt_id not in valid_ids:
                return (
                    f"Invalid prompt_id '{prompt_id}'. "
                    "Use list_prompts() to find valid prompt IDs."
                )
            match = (
                next((p for p in prompts if p.get("id") == prompt_id), None)
                if isinstance(prompts, list)
                else None
            )
            if match:
                resolved["prompt_name"] = match.get("name", "")
        params: dict = {"name": name, "base_concept": base_concept}
        if prompt_id:
            params["prompt_id"] = prompt_id
        return _propose_job(
            "production", f"Create production: {name}", params, resolved
        )

    async def list_prompt_categories():
        """List all available prompt categories. Call this first to discover
        what categories exist before listing prompts."""
        cats = await agent_tools.list_prompt_categories(invite_code)
        if isinstance(cats, list) and cats:
            lines = []
            for c in cats:
                examples = ", ".join(c.get("examples", []))
                lines.append(f"- {c['id']} ({c['count']} prompts) e.g. {examples}")
            return "Available prompt categories:\n" + "\n".join(lines)
        return "No prompt categories found."

    async def list_prompts(category: str):
        """List system prompts for a category. The category must be an exact
        category ID from list_prompt_categories(). Match user intent to the
        closest category (e.g. user says 'ads' → use 'production-ad')."""
        prompts = await agent_tools.list_system_prompts(invite_code, category)
        _request_context.get().update({"prompt_picker": category})
        if isinstance(prompts, list) and prompts:
            lines = [
                f"- {p.get('name', 'Unnamed')} (ID: {p.get('id', '?')}): "
                f"{p.get('description', '')}"
                for p in prompts
            ]
            return f"Prompts for '{category}':\n" + "\n".join(lines)
        return f"No prompts found for '{category}'. Call list_prompt_categories() to see valid names."

    return LlmAgent(
        name="director",
        model=model,
        instruction=(
            f"{STRICT_SCOPE_INSTRUCTION}\n"
            "You are the Production Director. You manage video projects and scripts.\n"
            "IMPORTANT: Call list_prompt_categories() to discover categories (with example "
            "prompt names), then match the user's intent to the best-fitting category and "
            "call list_prompts(category) with the exact ID. Never ask the user to choose "
            "from raw category IDs — infer the best match from the examples and proceed.\n"
            "IMPORTANT: Use propose_production() to create a confirmation card. "
            "Never execute jobs directly — always let the user review and confirm first."
        ),
        tools=[
            FunctionTool(func=list_recent_productions),
            FunctionTool(func=propose_production),
            FunctionTool(func=list_prompt_categories),
            FunctionTool(func=list_prompts),
            FunctionTool(func=_make_check_job_status(invite_code)),
        ],
    )


def create_editor_agent(invite_code: str, model: Gemini) -> LlmAgent:
    async def list_recent_reframes(limit: int = 5):
        """List the most recent video reframe (orientation) jobs."""
        return await agent_tools.list_recent_reframes(invite_code, limit)

    async def list_recent_key_moments(limit: int = 5):
        """List the most recent key moments analysis jobs."""
        return await agent_tools.list_recent_key_moments(invite_code, limit)

    async def list_recent_thumbnails(limit: int = 5):
        """List the most recent thumbnail jobs."""
        return await agent_tools.list_recent_thumbnails(invite_code, limit)

    async def list_content_types():
        """List valid content types for video reframing. Call this before
        reframe_video to pick the right content_type."""
        types = await agent_tools.list_content_types(invite_code)
        if isinstance(types, list) and types:
            lines = [
                f"- {t['id']}: {t.get('description', '')} (strategy: {t.get('cv_strategy', '')})"
                for t in types
            ]
            return "Available content types:\n" + "\n".join(lines)
        return "No content types found."

    async def propose_reframe(
        gcs_uri: str, content_type: str = "other", source_filename: str = ""
    ):
        """Propose a video reframe (orientation change). Does NOT execute — returns a confirmation card."""
        valid = await agent_tools.list_content_types(invite_code)
        valid_ids = [t["id"] for t in valid] if isinstance(valid, list) else []
        if valid_ids and content_type not in valid_ids:
            return (
                f"Invalid content_type '{content_type}'. "
                f"Valid options: {', '.join(valid_ids)}"
            )
        content_label = (
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
        display_name = source_filename or gcs_uri.rsplit("/", 1)[-1]
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
            {"source_name": display_name, "content_type_label": content_label},
        )

    async def propose_key_moments(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose a Key Moments analysis. Does NOT execute — returns a confirmation card."""
        resolved: dict = {}
        prompts = await agent_tools.list_system_prompts(invite_code, category=None)
        match = (
            next((p for p in prompts if p.get("id") == prompt_id), None)
            if isinstance(prompts, list)
            else None
        )
        if match:
            resolved["prompt_name"] = match.get("name", "")
        display_name = source_filename or gcs_uri.rsplit("/", 1)[-1]
        resolved["source_name"] = display_name
        return _propose_job(
            "key_moments",
            "Analyze key moments",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            resolved,
        )

    async def propose_thumbnails(
        gcs_uri: str, prompt_id: str, source_filename: str = ""
    ):
        """Propose a thumbnail generation/analysis. Does NOT execute — returns a confirmation card."""
        resolved: dict = {}
        prompts = await agent_tools.list_system_prompts(invite_code, category=None)
        match = (
            next((p for p in prompts if p.get("id") == prompt_id), None)
            if isinstance(prompts, list)
            else None
        )
        if match:
            resolved["prompt_name"] = match.get("name", "")
        display_name = source_filename or gcs_uri.rsplit("/", 1)[-1]
        resolved["source_name"] = display_name
        return _propose_job(
            "thumbnails",
            "Generate thumbnails",
            {
                "gcs_uri": gcs_uri,
                "prompt_id": prompt_id,
                "video_filename": source_filename,
            },
            resolved,
        )

    return LlmAgent(
        name="editor",
        model=model,
        instruction=(
            f"{STRICT_SCOPE_INSTRUCTION}\n"
            "You are the Video Editor. You process existing videos (reframe, key moments, thumbnails).\n"
            "IMPORTANT: Call list_content_types() before reframing to pick the correct content type.\n"
            "IMPORTANT: Use propose_* tools to create confirmation cards. "
            "Never execute jobs directly — always let the user review and confirm first."
        ),
        tools=[
            FunctionTool(func=list_recent_reframes),
            FunctionTool(func=list_recent_key_moments),
            FunctionTool(func=list_recent_thumbnails),
            FunctionTool(func=list_content_types),
            FunctionTool(func=propose_reframe),
            FunctionTool(func=propose_key_moments),
            FunctionTool(func=propose_thumbnails),
            FunctionTool(func=_make_list_available_videos(invite_code)),
            FunctionTool(func=_make_check_job_status(invite_code)),
        ],
    )


def create_marketer_agent(invite_code: str, model: Gemini) -> LlmAgent:
    async def list_recent_promos(limit: int = 5):
        """List the most recent promotional video jobs."""
        return await agent_tools.list_recent_promos(invite_code, limit)

    async def list_recent_adapts(limit: int = 5):
        """List the most recent social media adaptation jobs."""
        return await agent_tools.list_recent_adapts(invite_code, limit)

    async def list_adapt_options():
        """List valid aspect ratios and preset bundles for adapt jobs.
        Call this before adapt_video_platforms to show the user valid options."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        if isinstance(data, dict):
            lines = []
            bundles = data.get("preset_bundles", {})
            if bundles:
                lines.append("Preset bundles:")
                for k, v in bundles.items():
                    lines.append(f"  - {k} ({v['name']}): {', '.join(v['ratios'])}")
            ratios = data.get("ratios", [])
            if ratios:
                lines.append(f"All valid ratios: {', '.join(ratios)}")
            return "\n".join(lines)
        return "Could not fetch adapt options."

    async def propose_promo(
        gcs_uri: str,
        target_duration: int = 60,
        source_filename: str = "",
        text_overlay: bool = False,
    ):
        """Propose a new promotional video job. Does NOT execute — returns a confirmation card."""
        display_name = source_filename or gcs_uri.rsplit("/", 1)[-1]
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
            {"source_name": display_name},
        )

    async def propose_adapts(
        gcs_uri: str, aspect_ratios: List[str], source_filename: str = ""
    ):
        """Propose an Adapt job to resize video for multiple platforms. Does NOT execute — returns a confirmation card.
        Use list_adapt_options() first to discover valid ratios and presets."""
        data = await agent_tools.list_aspect_ratios(invite_code)
        valid_ratios = data.get("ratios", []) if isinstance(data, dict) else []
        if valid_ratios:
            invalid = [r for r in aspect_ratios if r not in valid_ratios]
            if invalid:
                return (
                    f"Invalid aspect ratios: {', '.join(invalid)}. "
                    f"Valid options: {', '.join(valid_ratios)}"
                )
        display_name = source_filename or gcs_uri.rsplit("/", 1)[-1]
        return _propose_job(
            "adapts",
            f"Adapt for {len(aspect_ratios)} platforms",
            {
                "gcs_uri": gcs_uri,
                "source_filename": source_filename,
                "aspect_ratios": aspect_ratios,
            },
            {"source_name": display_name},
        )

    return LlmAgent(
        name="marketer",
        model=model,
        instruction=(
            f"{STRICT_SCOPE_INSTRUCTION}\n"
            "You are the Marketing Expert. You create promos and social adaptations.\n"
            "IMPORTANT: Call list_adapt_options() before creating adapts to show the user "
            "valid aspect ratios and preset bundles.\n"
            "IMPORTANT: Use propose_* tools to create confirmation cards. "
            "Never execute jobs directly — always let the user review and confirm first."
        ),
        tools=[
            FunctionTool(func=list_recent_promos),
            FunctionTool(func=list_recent_adapts),
            FunctionTool(func=list_adapt_options),
            FunctionTool(func=propose_promo),
            FunctionTool(func=propose_adapts),
            FunctionTool(func=_make_list_available_videos(invite_code)),
            FunctionTool(func=_make_check_job_status(invite_code)),
        ],
    )


# ── Public API ───────────────────────────────────────────────────────


def create_orchestrator(invite_code: str):
    """The central Router agent that delegates to specialists."""
    _request_context.set({})
    model = _create_model()

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
        feature-specific inputs:
        - production: scene_count and/or video_length_seconds
        - adapts: variant_count
        - reframe or key_moments: source_duration_seconds
        - promo: segment_count, has_title_card, source_duration_seconds
        - thumbnails: thumbnail_count, source_duration_seconds
        Returns a per-service breakdown plus a total_usd estimate."""
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
        estimated fields). Use when the user asks 'how much did job X cost?'
        or 'break down the cost for record Y'. `feature` is one of
        production/adapts/reframe/promo/key_moments/thumbnails."""
        return await agent_tools.get_job_cost(invite_code, feature, record_id)

    async def list_recent_jobs(feature: str, limit: int = 5):
        """List the most recent records for any feature, sorted newest-first.
        Returns [{id, name, status, createdAt}]. Use this FIRST to resolve
        relative references like 'my last production', 'the previous reframe',
        'my recent promos' — then call get_job_cost on the chosen record's id.
        `feature` is one of production/adapts/reframe/promo/key_moments/thumbnails."""
        return await agent_tools.list_recent_jobs(invite_code, feature, limit)

    return LlmAgent(
        name="Aanya",
        model=model,
        instruction=(
            f"{STRICT_SCOPE_INSTRUCTION}\n"
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
        ),
        tools=[
            FunctionTool(func=get_pricing_rates),
            FunctionTool(func=get_feature_services),
            FunctionTool(func=estimate_cost),
            FunctionTool(func=get_job_cost),
            FunctionTool(func=list_recent_jobs),
        ],
        sub_agents=[
            create_director_agent(invite_code, model),
            create_editor_agent(invite_code, model),
            create_marketer_agent(invite_code, model),
        ],
    )


def get_agent_context() -> dict:
    """Returns the accumulated context from the current request."""
    return _request_context.get()

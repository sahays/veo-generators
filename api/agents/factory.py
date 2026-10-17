"""Aanya orchestrator — pure intent router delegating to 8 feature-isolated specialists.

Each feature in Veo Generators has its own dedicated ADK specialist agent with
strictly scoped API tools and a Gemini model matched to its responsibility tier:
0. `Aanya` (Root Router) — `gemini-3.5-flash-lite` (0 domain tools; pure delegation)
1. `productions_agent` — Productions, Scripts, Storyboards, Prompts (`creative` tier)
2. `reframe_agent` — Vertical/Portrait Video Reframing (`specialist` tier)
3. `key_moments_agent` — Timestamped Key Moments Analysis (`specialist` tier)
4. `thumbnails_agent` — Video Thumbnail Analysis, Frame Capture & Collage (`specialist` tier)
5. `promo_agent` — Promotional Video Cutdowns (`specialist` tier)
6. `adapts_agent` — Social Media Image Adaptations (`specialist` tier)
7. `dubbing_agent` — Multi-Language Video Dubbing & Subtitles (`specialist` tier)
8. `finops_agent` — Pricing, Cost Estimates, Job Usage Breakdowns, Models & Uploads (`finops` tier)
"""

import time

from google.adk import Runner
from google.adk.agents import LlmAgent
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ._shared import (
    STRICT_SCOPE_INSTRUCTION,
    create_model,
    get_agent_context,
    reset_agent_context,
    sanitize_markdown_response,
)
from .specialists import (
    create_adapts_agent,
    create_director_agent,
    create_dubbing_agent,
    create_editor_agent,
    create_finops_agent,
    create_key_moments_agent,
    create_marketer_agent,
    create_productions_agent,
    create_promo_agent,
    create_reframe_agent,
    create_thumbnails_agent,
    make_finops_tools,
)

# Public re-exports for callers and tests
__all__ = [
    "create_adapts_agent",
    "create_director_agent",
    "create_dubbing_agent",
    "create_editor_agent",
    "create_finops_agent",
    "create_key_moments_agent",
    "create_marketer_agent",
    "create_orchestrator",
    "create_productions_agent",
    "create_promo_agent",
    "create_reframe_agent",
    "create_thumbnails_agent",
    "get_agent_context",
    "run_agent_chat",
    "_make_orchestrator_tools",
]

_EMPTY_ACTIONS = EventActions(
    artifact_delta={},
    requested_auth_configs={},
    requested_tool_confirmations={},
    state_delta={},
)

_ORCHESTRATOR_ROLE = (
    "Introduce yourself as Aanya, the Veo AI Orchestrator. "
    "You are a pure router with 8 dedicated feature specialist sub-agents. "
    "Delegate every user request based on feature intent:\n"
    "1. 'productions_agent': New video/ad productions, scripts, storyboards, scene videos, "
    "stitching, or browsing system prompts/templates/categories.\n"
    "2. 'reframe_agent': Reframing videos to vertical/portrait (9:16, 3:4) or checking orientations.\n"
    "3. 'key_moments_agent': Analyzing videos to find timestamped key moments or highlights.\n"
    "4. 'thumbnails_agent': Generating video thumbnails, capturing frames, or building collages.\n"
    "5. 'promo_agent': Creating promotional trailer/cutdown videos from a source video.\n"
    "6. 'adapts_agent': Adapting/outpainting an image across multiple social aspect ratios.\n"
    "7. 'dubbing_agent': Translating and dubbing videos into target languages (Spanish, Hindi, French, etc.).\n"
    "8. 'finops_agent': Pricing rates, feature service maps, pre-job cost estimates, "
    "post-job cost breakdowns, token consumption / usage metrics for any job, registered AI models, and uploaded files inventory.\n\n"
    "IMPORTANT: Any question about tokens consumed, usage, cost, or billing for a job "
    "(e.g. 'how many tokens consumed for the last Orientations job?') goes to 'finops_agent'.\n"
    "Distinguish 'prompts' (system prompt templates → 'productions_agent') "
    "from 'promos' (promotional video cutdowns → 'promo_agent').\n"
    "When a specialist proposes a job, an interactive A2UI confirmation card appears "
    "automatically in the Ask Aanya chat UI for the user to review, adjust, and confirm."
)

# Backward-compatible alias for unit tests inspecting FinOps tools
_make_orchestrator_tools = make_finops_tools


def create_orchestrator(invite_code: str) -> LlmAgent:
    """Create the root Aanya Router agent (0 direct tools) with 8 feature-isolated sub-agents."""
    reset_agent_context()
    router_model = create_model("router")
    specialist_model = create_model("specialist")
    creative_model = create_model("creative")
    finops_model = create_model("finops")

    return LlmAgent(
        name="Aanya",
        model=router_model,
        instruction=f"{STRICT_SCOPE_INSTRUCTION}\n{_ORCHESTRATOR_ROLE}",
        tools=[],
        sub_agents=[
            create_productions_agent(invite_code, creative_model),
            create_reframe_agent(invite_code, specialist_model),
            create_key_moments_agent(invite_code, specialist_model),
            create_thumbnails_agent(invite_code, specialist_model),
            create_promo_agent(invite_code, specialist_model),
            create_adapts_agent(invite_code, specialist_model),
            create_dubbing_agent(invite_code, specialist_model),
            create_finops_agent(invite_code, finops_model),
        ],
    )


async def run_agent_chat(
    invite_code: str, message: str, history: list[tuple[str, str]]
) -> dict:
    """Execute a turn of the Aanya ADK multi-agent hierarchy and return the chat response."""
    t0 = time.perf_counter()
    orchestrator = create_orchestrator(invite_code)
    session_service = InMemorySessionService()
    runner = Runner(
        app_name="VeoGen",
        agent=orchestrator,
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="VeoGen",
        user_id=invite_code,
        session_id=invite_code,
    )
    for role, content in history:
        await session_service.append_event(
            session,
            Event(
                author="user" if role == "user" else "Aanya",
                content=types.Content(role=role, parts=[types.Part(text=content)]),
                actions=_EMPTY_ACTIONS,
                timestamp=time.time(),
            ),
        )

    msg = types.Content(role="user", parts=[types.Part(text=message)])
    full_response = ""
    last_agent = "Aanya"

    async for event in runner.run_async(
        user_id=invite_code, session_id=invite_code, new_message=msg
    ):
        if event.content:
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    full_response += part.text
        if event.author:
            last_agent = event.author

    latency_ms = max(1, round((time.perf_counter() - t0) * 1000))
    return {
        "response": sanitize_markdown_response(full_response),
        "role": "model",
        "agent": last_agent,
        "latency_ms": latency_ms,
        "data": get_agent_context().copy(),
    }

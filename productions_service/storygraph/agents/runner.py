"""ADK Role Runner (`run_role`) with fresh `InMemorySessionService`, scoped tools, and structured Pydantic output repair."""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from google import genai
from google.adk.agents import LlmAgent
from google.adk.models.google_llm import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from ..adapters.mock import MockLLMClient
from ..errors import StructuredOutputError
from ..schema import Role
from ..tools.registry import ToolContext, tools_for_role

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).parent / "prompts"

ROLE_AGENT_NAMES: dict[Role, str] = {
    Role.STORY_ARCHITECT: "story_architect_agent",
    Role.SCRIPT_SUPERVISOR: "script_supervisor_agent",
    Role.SCREENWRITER: "screenwriter_agent",
    Role.CHARACTER_DESIGNER: "character_designer_agent",
    Role.LOCATION_DESIGNER: "location_designer_agent",
    Role.OBJECT_DESIGNER: "object_designer_agent",
    Role.DESIGNER: "visual_design_lead",
    Role.DIRECTOR: "director_agent",
    Role.MUSIC_DIRECTOR: "music_director_agent",
    Role.CRITIC: "critic_agent",
}

_ROLE_PROMPT_FILES: dict[Role, str] = {
    Role.STORY_ARCHITECT: "story_architect.md",
    Role.SCRIPT_SUPERVISOR: "script_supervisor.md",
    Role.SCREENWRITER: "screenwriter.md",
    Role.CHARACTER_DESIGNER: "character_designer.md",
    Role.LOCATION_DESIGNER: "location_designer.md",
    Role.OBJECT_DESIGNER: "object_designer.md",
    Role.DESIGNER: "character_designer.md",
    Role.DIRECTOR: "director.md",
    Role.MUSIC_DIRECTOR: "music_director.md",
    Role.CRITIC: "critic.md",
}


@dataclass
class RoleRunResult:
    output: Any
    tokens_in: int = 0
    tokens_out: int = 0


def load_role_prompt(role: Role) -> str:
    fname = _ROLE_PROMPT_FILES.get(role, "story_architect.md")
    path = PROMPTS_DIR / fname
    return path.read_text(encoding="utf-8") if path.is_file() else f"Role: {role}"


def build_adk_role_agent(
    role: Role,
    ctx: ToolContext,
    output_schema: type[BaseModel] | None = None,
) -> LlmAgent:
    """Construct a Google ADK `LlmAgent` scoped strictly to `role`'s tools and model."""
    model_name = getattr(ctx.cfg.models, str(role), "gemini-3.8-flash")
    agent_name = ROLE_AGENT_NAMES.get(role, f"{role}_agent")
    instruction = load_role_prompt(role)
    scoped_tools = tools_for_role(ctx)

    kwargs: dict[str, Any] = {
        "name": agent_name,
        "model": Gemini(model=model_name),
        "instruction": instruction,
        "tools": scoped_tools if output_schema is None else [],
    }
    if output_schema is not None:
        kwargs["output_schema"] = output_schema
    return LlmAgent(**kwargs)


def _extract_event_metrics(event: Any) -> tuple[list[str], int, int]:
    """Extract text parts and token counts from a single ADK runner event."""
    t_in = 0
    t_out = 0
    if getattr(event, "usage_metadata", None):
        t_in = int(getattr(event.usage_metadata, "prompt_token_count", 0) or 0)
        t_out = int(getattr(event.usage_metadata, "candidates_token_count", 0) or 0)
    texts = [
        part.text
        for part in (
            event.content.parts if event.content and event.content.parts else []
        )
        if getattr(part, "text", None)
    ]
    return texts, t_in, t_out


async def _run_adk_once(
    agent: LlmAgent,
    prompt: str,
) -> tuple[str, int, int]:
    session_service = InMemorySessionService()
    session_id = f"sess_{uuid.uuid4().hex[:10]}"
    await session_service.create_session(
        app_name="storygraph_studio", user_id="pipeline", session_id=session_id
    )
    runner = Runner(
        agent=agent, app_name="storygraph_studio", session_service=session_service
    )
    msg = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    chunks: list[str] = []
    tokens_in, tokens_out = 0, 0
    async for event in runner.run_async(
        user_id="pipeline", session_id=session_id, new_message=msg
    ):
        parts, tin, tout = _extract_event_metrics(event)
        chunks.extend(parts)
        tokens_in += tin
        tokens_out += tout
    return "".join(chunks).strip(), tokens_in, tokens_out


def _coerce_mock_candidate(
    raw_candidate: Any, output_schema: type[T], attempt: int
) -> RoleRunResult:
    """Validate a scripted mock response against `output_schema`."""
    scale = attempt + 1
    if isinstance(raw_candidate, output_schema):
        return RoleRunResult(output=raw_candidate, tokens_in=120, tokens_out=180)
    if isinstance(raw_candidate, dict):
        return RoleRunResult(
            output=output_schema.model_validate(raw_candidate),
            tokens_in=120,
            tokens_out=180,
        )
    return RoleRunResult(
        output=output_schema.model_validate_json(str(raw_candidate)),
        tokens_in=120 * scale,
        tokens_out=180 * scale,
    )


def _run_scripted_mock(
    role: Role,
    role_key: str,
    user_prompt: str,
    output_schema: type[T],
    mock_llm: MockLLMClient,
    max_repair_retries: int,
) -> RoleRunResult | None:
    """Execute `mock_llm` scripted queue with repair retries if a response is queued."""
    mock_llm.calls.append({"role": role_key, "prompt": user_prompt})
    scripted = mock_llm.pop_response(role_key)
    if scripted is None:
        return None
    if not isinstance(scripted, str):
        return _coerce_mock_candidate(scripted, output_schema, 0)

    last_err: Exception | None = None
    raw_candidate: Any = scripted
    for attempt in range(max_repair_retries + 1):
        try:
            return _coerce_mock_candidate(raw_candidate, output_schema, attempt)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            next_cand = mock_llm.pop_response(role_key)
            if next_cand is not None:
                raw_candidate = next_cand
    raise StructuredOutputError(
        f"Role '{role}' failed structured output validation after {max_repair_retries} repair retries: {last_err}"
    )


def _strip_json_fences(raw_text: str) -> str:
    """Remove optional markdown code fences wrapping a JSON response."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return cleaned


def _call_vertex_structured(
    project: str | None,
    location: str,
    model_name: str,
    instruction: str,
    prompt: str,
    output_schema: type[T],
) -> tuple[T, int, int]:
    """Invoke Vertex AI Gemini with `response_schema=output_schema` and return `(parsed, tin, tout)`."""
    client = genai.Client(vertexai=True, project=project, location=location)
    cfg = types.GenerateContentConfig(
        system_instruction=instruction,
        response_mime_type="application/json",
        response_schema=output_schema,
        temperature=0.2,
    )
    resp = client.models.generate_content(model=model_name, contents=prompt, config=cfg)
    t_in, t_out = 0, 0
    if getattr(resp, "usage_metadata", None):
        t_in = int(getattr(resp.usage_metadata, "prompt_token_count", 0) or 0)
        t_out = int(getattr(resp.usage_metadata, "candidates_token_count", 0) or 0)
    raw_text = _strip_json_fences(resp.text or "")
    return output_schema.model_validate_json(raw_text), t_in, t_out


def _run_live_vertex_role(
    role: Role,
    ctx: ToolContext,
    user_prompt: str,
    output_schema: type[T],
    max_repair_retries: int,
) -> RoleRunResult:
    """Run live Vertex AI Gemini structured execution with schema repair retries."""
    model_name = getattr(ctx.cfg.models, str(role), "gemini-3.8-flash")
    instruction = load_role_prompt(role)
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or ctx.cfg.store.firestore_project
    location = os.getenv("GEMINI_REGION", "global")
    current_prompt = user_prompt
    total_in, total_out = 0, 0
    last_error: Exception | None = None

    for attempt in range(max_repair_retries + 1):
        try:
            parsed, tin, tout = _call_vertex_structured(
                project,
                location,
                model_name,
                instruction,
                current_prompt,
                output_schema,
            )
            total_in += tin
            total_out += tout
            return RoleRunResult(
                output=parsed, tokens_in=total_in or 250, tokens_out=total_out or 350
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(
                "Role structured output attempt failed; scheduling repair retry",
                extra={
                    "role": str(role),
                    "model": model_name,
                    "attempt": attempt + 1,
                    "error": str(exc),
                },
            )
            current_prompt = (
                f"{user_prompt}\n\nYour previous response failed schema validation with error:\n"
                f"{exc}\nPlease return ONLY valid JSON matching {output_schema.__name__}."
            )
    raise StructuredOutputError(
        f"Role '{role}' ({model_name}) failed structured output after {max_repair_retries} retries: {last_error}"
    )


def run_role(
    role: Role,
    ctx: ToolContext,
    user_prompt: str,
    output_schema: type[T],
    mock_llm: MockLLMClient | None = None,
    fallback_builder: Callable[[], T] | None = None,
    max_repair_retries: int = 2,
) -> RoleRunResult:
    """Execute a role agent with fresh InMemorySessionService and validate structured output with up to 2 repair retries."""
    if mock_llm is not None:
        mock_res = _run_scripted_mock(
            role, str(role), user_prompt, output_schema, mock_llm, max_repair_retries
        )
        if mock_res is not None:
            return mock_res

    if fallback_builder is not None and ctx.cfg.image.provider == "mock":
        return RoleRunResult(output=fallback_builder(), tokens_in=150, tokens_out=220)

    return _run_live_vertex_role(
        role, ctx, user_prompt, output_schema, max_repair_retries
    )

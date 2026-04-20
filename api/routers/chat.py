import logging
import time
from typing import List

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from google.adk import Runner
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.runners import InMemorySessionService, types
from agents.factory import create_orchestrator, get_agent_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_EMPTY_ACTIONS = EventActions(
    artifact_delta={},
    requested_auth_configs={},
    requested_tool_confirmations={},
    state_delta={},
)


class ChatMessage(BaseModel):
    role: str  # 'user' or 'model'
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


@router.post("")
async def chat_endpoint(body: ChatRequest, request: Request):
    """Chat with the Veo AI Multi-Agent system."""
    invite_code = getattr(request.state, "invite_code", None)
    if not invite_code:
        raise HTTPException(status_code=403, detail="Invite code required for chat")

    try:
        orchestrator = create_orchestrator(invite_code)

        session_service = InMemorySessionService()
        runner = Runner(
            app_name="VeoGen",
            agent=orchestrator,
            session_service=session_service,
            auto_create_session=True,
        )

        # Seed conversation history so the agent has context from prior turns.
        if body.history:
            session = await session_service.create_session(
                app_name="VeoGen",
                user_id=invite_code,
                session_id=invite_code,
            )
            for msg in body.history:
                await session_service.append_event(
                    session,
                    Event(
                        author="user" if msg.role == "user" else "Aanya",
                        content=types.Content(
                            role=msg.role, parts=[types.Part(text=msg.content)]
                        ),
                        actions=_EMPTY_ACTIONS,
                        timestamp=time.time(),
                    ),
                )

        msg = types.Content(role="user", parts=[types.Part(text=body.message)])

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

        return {
            "response": full_response,
            "role": "model",
            "agent": last_agent,
            "data": get_agent_context().copy(),
        }
    except Exception:
        logger.exception("Error in chat orchestrator")
        raise HTTPException(
            status_code=500,
            detail="An error occurred processing your request. Please try again.",
        )

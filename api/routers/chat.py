import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import deps
from agents.factory import run_agent_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

# In-memory fallback when Firestore isn't initialized (e.g., unit tests).
_MEMORY_SHARED_CHATS: dict[str, dict] = {}


class ChatMessage(BaseModel):
    role: str  # 'user' or 'model'
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


class SharedChatItem(BaseModel):
    role: str
    content: str
    agent: Optional[str] = None
    latency_ms: Optional[int] = None
    timestamp: Optional[int] = None


class ShareChatRequest(BaseModel):
    title: Optional[str] = None
    messages: List[SharedChatItem]


@router.post("")
async def chat_endpoint(body: ChatRequest, request: Request):
    """Chat with the Veo AI Multi-Agent system."""
    invite_code = getattr(request.state, "invite_code", None)
    if not invite_code:
        raise HTTPException(status_code=403, detail="Invite code required for chat")

    try:
        return await run_agent_chat(
            invite_code=invite_code,
            message=body.message,
            history=[(m.role, m.content) for m in body.history],
        )
    except Exception:
        logger.exception("Error in chat orchestrator")
        raise HTTPException(
            status_code=500,
            detail="An error occurred processing your request. Please try again.",
        )


@router.post("/share")
async def create_shared_chat(body: ShareChatRequest, request: Request):
    """Create a publicly shareable snapshot of a chat conversation."""
    invite_code = getattr(request.state, "invite_code", None)
    if not invite_code:
        raise HTTPException(status_code=403, detail="Invite code required")
    if not body.messages:
        raise HTTPException(status_code=400, detail="Cannot share an empty chat")

    first_user = next(
        (
            m.content.strip()
            for m in body.messages
            if m.role == "user" and m.content.strip()
        ),
        "Ask Aanya Conversation",
    )
    title = (body.title or first_user)[:80]
    share_id = f"sh-{uuid.uuid4().hex[:8]}"
    created_at = datetime.now(timezone.utc).isoformat()
    record = {
        "id": share_id,
        "title": title,
        "created_at": created_at,
        "messages": [m.model_dump() for m in body.messages],
    }

    if deps.firestore_svc:
        deps.firestore_svc.create_shared_chat(share_id, record)
    else:
        _MEMORY_SHARED_CHATS[share_id] = record

    return {"id": share_id, "title": title, "created_at": created_at}


@router.get("/share/{share_id}")
async def get_shared_chat(share_id: str):
    """Publicly retrieve a shared chat conversation by ID."""
    record = (
        deps.firestore_svc.get_shared_chat(share_id)
        if deps.firestore_svc
        else _MEMORY_SHARED_CHATS.get(share_id)
    )
    if not record:
        raise HTTPException(status_code=404, detail="Shared chat not found")
    return record

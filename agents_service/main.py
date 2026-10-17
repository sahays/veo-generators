"""Dedicated Cloud Run microservice for the 9-Agent Gemini ADK hierarchy (`veo-generators-agents`).

Maintains strict runtime isolation and separation of duties:
- Zero Firestore, GCS, OpenCV, or FFmpeg dependencies.
- All agent tool calls execute over HTTP/REST against `VEOGEN_API_ORIGIN`
  forwarding the caller's `X-Invite-Code` header.
"""

from contextlib import asynccontextmanager
import logging
import os
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from agents.factory import run_agent_chat
from agents.tools import close_client
from agents.tools._client import api_call

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await close_client()


app = FastAPI(
    title="Veo Generators — ADK Multi-Agent Orchestrator Service",
    lifespan=lifespan,
)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []


async def _verify_invite_code(invite_code: str) -> None:
    if not invite_code:
        raise HTTPException(status_code=403, detail="Invite code required for chat")
    master_code = os.getenv("MASTER_INVITE_CODE", "")
    if master_code and invite_code == master_code:
        return
    auth_res = await api_call(
        "POST", "/api/v1/auth/validate", invite_code, json={"code": invite_code}
    )
    if not isinstance(auth_res, dict) or not auth_res.get("valid"):
        raise HTTPException(status_code=403, detail="Invalid or expired invite code")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "veo-generators-agents",
        "agents": 9,
    }


@app.post("/api/v1/chat")
async def chat_endpoint(body: ChatRequest, request: Request):
    invite_code = request.headers.get("X-Invite-Code", "")
    await _verify_invite_code(invite_code)
    try:
        return await run_agent_chat(
            invite_code=invite_code,
            message=body.message,
            history=[(m.role, m.content) for m in body.history],
        )
    except Exception:
        logger.exception("Error in ADK multi-agent orchestrator")
        raise HTTPException(
            status_code=500,
            detail="An error occurred processing your request. Please try again.",
        )

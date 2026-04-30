"""Avatar feature router — CRUD + per-turn Q&A (v1).

The v2 (Low Latency) live session — `/live-config` and the `/live` WebSocket
proxy — lives in `routers.avatars_live`. Both routers mount under
`/api/v1/avatars`.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

import deps
import avatar_service
from helpers import get_or_404, require_firestore, sign_record_urls
from models import (
    AskAvatarRequest,
    Avatar,
    AvatarStyle,
    AvatarTurn,
    AvatarVoice,
    CreateAvatarRequest,
)
from routers._crud import register_crud_routes


class UpdateAvatarRequest(BaseModel):
    name: Optional[str] = None
    style: Optional[AvatarStyle] = None
    persona_prompt: Optional[str] = None
    voice: Optional[AvatarVoice] = None  # v2 only


VOICE_TURN_MARKER = "__voice__"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/avatars", tags=["avatars"])


def _sign_avatar(record: Avatar) -> dict:
    return sign_record_urls(
        record,
        {"image_gcs_uri": "image_signed_url"},
        lambda cache: deps.firestore_svc.update_avatar(
            record.id, {"signed_urls": cache}
        ),
    )


def _sign_turn(record: AvatarTurn) -> dict:
    return sign_record_urls(
        record,
        {"video_gcs_uri": "video_signed_url"},
        lambda cache: deps.firestore_svc.update_avatar_turn(
            record.id, {"signed_urls": cache}
        ),
    )


def _require_v1(avatar: Avatar) -> None:
    if avatar.version != "v1":
        raise HTTPException(
            409,
            "This avatar uses the v2 (Low Latency) live session — use the live "
            "WebSocket endpoint instead of /ask.",
        )


# Standard CRUD: list / get / archive / delete (PATCH is custom — see below).
register_crud_routes(
    router,
    resource_label="Avatar",
    getter=lambda rid: deps.firestore_svc.get_avatar(rid),
    updater=lambda rid, u: deps.firestore_svc.update_avatar(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_avatar(rid),
    lister=lambda include_archived=False: deps.firestore_svc.get_avatars(
        include_archived=include_archived
    ),
    sign_one=_sign_avatar,
    include_patch=False,
    include_retry=False,
)


def _collect_avatar_updates(body: UpdateAvatarRequest, avatar: Avatar) -> dict:
    """Translate the patch payload into a Firestore update dict, validating
    the v2-only `voice` field."""
    updates: dict = {}
    if body.name is not None:
        n = body.name.strip()
        if n:
            updates["name"] = n
    if body.style is not None:
        updates["style"] = body.style.value
    if body.persona_prompt is not None:
        updates["persona_prompt"] = body.persona_prompt.strip()
    if body.voice is not None:
        if avatar.version != "v2":
            raise HTTPException(400, "voice is only valid for v2 avatars")
        updates["voice"] = body.voice.value
    return updates


@router.patch("/{avatar_id}")
async def update_avatar(avatar_id: str, body: UpdateAvatarRequest):
    """Update an avatar's name, style, persona, or (v2 only) voice."""
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    updates = _collect_avatar_updates(body, avatar)
    if not updates:
        raise HTTPException(400, "No valid fields to update")
    deps.firestore_svc.update_avatar(avatar.id, updates)
    return {"status": "updated"}


@router.post("")
async def create_avatar(body: CreateAvatarRequest):
    """Create a new avatar — v1 from an uploaded portrait, v2 from a preset
    or upload."""
    require_firestore()
    # Only validate the gs:// URI when one is actually supplied (v2 with a
    # preset_name skips the upload entirely).
    if body.image_gcs_uri:
        if not body.image_gcs_uri.startswith("gs://"):
            raise HTTPException(400, "image_gcs_uri must be a gs:// URI")
        if deps.storage_svc and not deps.storage_svc.blob_exists(body.image_gcs_uri):
            raise HTTPException(400, "Avatar image not found in GCS")
    avatar = Avatar(
        name=body.name.strip() or "Untitled",
        image_gcs_uri=body.image_gcs_uri,
        style=body.style,
        persona_prompt=body.persona_prompt.strip(),
        version=body.version,
        voice=body.voice,
        preset_name=body.preset_name,
        language=body.language or "en-US",
        default_greeting=(body.default_greeting or "").strip(),
        enable_grounding=body.enable_grounding,
    )
    deps.firestore_svc.create_avatar(avatar)
    return _sign_avatar(avatar)


@router.post("/{avatar_id}/ask")
async def ask_avatar(avatar_id: str, body: AskAvatarRequest, request: Request):
    """Generate a text answer immediately and queue a Veo render for the
    lip-synced video. (v1 only)"""
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    _require_v1(avatar)
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(400, "Question must not be empty")

    answer_text, usage, text_model = avatar_service.answer_question(
        avatar=avatar,
        question=question,
        history=body.history,
        model_id=body.model_id,
        region=body.region,
    )
    if not answer_text:
        raise HTTPException(502, "Model returned no text")

    turn = avatar_service.create_pending_turn(
        avatar=avatar,
        question=question,
        answer_text=answer_text,
        usage=usage,
        text_model_id=text_model,
        invite_code=getattr(request.state, "invite_code", None),
        region=body.region,
    )
    return {"turn_id": turn.id, "answer_text": answer_text, "status": turn.status}


def _parse_audio_history(raw: Optional[str]) -> list[dict]:
    if not raw:
        return []
    try:
        return json.loads(raw) or []
    except json.JSONDecodeError:
        return []


def _validate_audio_payload(audio_bytes: bytes) -> None:
    if not audio_bytes:
        raise HTTPException(400, "Audio payload is empty")
    if len(audio_bytes) > 10 * 1024 * 1024:  # 10 MB ceiling for ≤ 10 s opus
        raise HTTPException(413, "Audio payload too large")


@router.post("/{avatar_id}/ask-audio")
async def ask_avatar_audio(
    avatar_id: str,
    request: Request,
    audio: UploadFile = File(...),
    history: Optional[str] = Form(None),
    model_id: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
):
    """Voice variant of /ask. (v1 only) Frontend sends a raw audio blob captured
    via MediaRecorder; we forward bytes to Gemini multimodal so it both
    understands the question and produces a reply."""
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    _require_v1(avatar)

    audio_bytes = await audio.read()
    _validate_audio_payload(audio_bytes)

    try:
        answer_text, usage, text_model = avatar_service.answer_audio_question(
            avatar=avatar,
            audio_bytes=audio_bytes,
            mime_type=audio.content_type or "audio/webm",
            history=_parse_audio_history(history),
            model_id=model_id,
            region=region,
        )
    except Exception as e:
        logger.error(f"answer_audio_question failed: {e}")
        raise HTTPException(502, f"Could not understand audio: {e}")

    if not answer_text:
        raise HTTPException(502, "Model returned no text")

    turn = avatar_service.create_pending_turn(
        avatar=avatar,
        question=VOICE_TURN_MARKER,
        answer_text=answer_text,
        usage=usage,
        text_model_id=text_model,
        invite_code=getattr(request.state, "invite_code", None),
        region=region,
    )
    return {"turn_id": turn.id, "answer_text": answer_text, "status": turn.status}


@router.get("/{avatar_id}/turns")
async def list_avatar_turns(avatar_id: str):
    require_firestore()
    get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    turns = deps.firestore_svc.get_avatar_turns(avatar_id=avatar_id)
    return [_sign_turn(t) for t in turns]


@router.get("/turns/{turn_id}")
async def get_avatar_turn(turn_id: str):
    require_firestore()
    turn = get_or_404(deps.firestore_svc.get_avatar_turn, turn_id, "Avatar turn")
    return _sign_turn(turn)

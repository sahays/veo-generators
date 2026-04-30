"""Avatar feature router — CRUD + per-turn Q&A (v1) + Live session proxy (v2)."""

import asyncio
import base64
import json
import logging
import os
from typing import Optional

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)

import deps
import avatar_service
from gcp_auth import vertex_access_token
from helpers import get_or_404, require_firestore, sign_record_urls
from models import (
    AskAvatarRequest,
    Avatar,
    AvatarStyle,
    AvatarTurn,
    AvatarVoice,
    CreateAvatarRequest,
)
from pydantic import BaseModel
from routers._crud import register_crud_routes


class UpdateAvatarRequest(BaseModel):
    name: Optional[str] = None
    style: Optional[AvatarStyle] = None
    persona_prompt: Optional[str] = None
    voice: Optional[AvatarVoice] = None  # v2 only


VOICE_TURN_MARKER = "__voice__"

# The Gemini Live Avatar preview is reachable via the "global" surface, which
# routes to the autopush sandbox host. The preview model is allowlisted on a
# specific GCP project (ffeldhaus-avatar-demo by default — change with
# AVATAR_LIVE_PROJECT). The model path *and* the x-goog-user-project header
# both need to point at that project so the autopush API check passes.
LIVE_MODEL = os.getenv("AVATAR_LIVE_MODEL", "gemini-3.1-flash-live-preview-04-2026")
LIVE_LOCATION_DEFAULT = "global"
LIVE_HOST_GLOBAL = "autopush-aiplatform.sandbox.googleapis.com"
LIVE_PROJECT_DEFAULT = "ffeldhaus-avatar-demo"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/avatars", tags=["avatars"])


def _live_location() -> str:
    # Live Avatar preview sits on the "global" surface; only override if the
    # operator explicitly sets a regional rollout via env.
    return os.getenv("AVATAR_LIVE_LOCATION") or LIVE_LOCATION_DEFAULT


def _live_host(location: str) -> str:
    if location == "global":
        return LIVE_HOST_GLOBAL
    return f"{location}-aiplatform.googleapis.com"


def _live_project() -> str:
    """The GCP project where the Gemini Live preview model is allowlisted.
    Distinct from GOOGLE_CLOUD_PROJECT (where this Cloud Run service runs)."""
    return os.getenv("AVATAR_LIVE_PROJECT") or LIVE_PROJECT_DEFAULT


def _load_avatar_image_b64(avatar: Avatar) -> tuple[str, str]:
    """Download the avatar's portrait from GCS and return (base64, mime).

    Required for `customizedAvatar` in the live session setup frame — the
    upstream API takes the image inline rather than a URL.
    """
    if not deps.storage_svc:
        raise RuntimeError("Storage service unavailable")
    raw = deps.storage_svc.download_bytes(avatar.image_gcs_uri)
    # Best-effort mime sniff — JPEG vs PNG covers the bulk of uploads.
    mime = "image/png" if raw[:8].startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    logger.info(
        f"[avatar:{avatar.id}] loaded portrait from {avatar.image_gcs_uri} "
        f"({len(raw)} bytes, mime={mime})"
    )
    return base64.b64encode(raw).decode("ascii"), mime


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


# Standard CRUD: list / get / archive / delete (PATCH is custom — see below)
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


@router.patch("/{avatar_id}")
async def update_avatar(avatar_id: str, body: UpdateAvatarRequest):
    """Update an avatar's name, style, persona, or (v2 only) voice. None means leave unchanged."""
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
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
    """Generate a text answer immediately and queue a Veo render for the lip-synced video. (v1 only)"""
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
    return {
        "turn_id": turn.id,
        "answer_text": answer_text,
        "status": turn.status,
    }


@router.post("/{avatar_id}/ask-audio")
async def ask_avatar_audio(
    avatar_id: str,
    request: Request,
    audio: UploadFile = File(...),
    history: Optional[str] = Form(None),
    model_id: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
):
    """Voice variant of /ask. (v1 only) Frontend sends a raw audio blob captured via
    MediaRecorder; we forward bytes to Gemini multimodal so it both
    understands the question and produces a reply."""
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    _require_v1(avatar)

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(400, "Audio payload is empty")
    if len(audio_bytes) > 10 * 1024 * 1024:  # 10 MB ceiling for ≤ 10 s opus
        raise HTTPException(413, "Audio payload too large")
    mime_type = audio.content_type or "audio/webm"

    history_list: list[dict] = []
    if history:
        try:
            history_list = json.loads(history) or []
        except json.JSONDecodeError:
            history_list = []

    try:
        answer_text, usage, text_model = avatar_service.answer_audio_question(
            avatar=avatar,
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            history=history_list,
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
    return {
        "turn_id": turn.id,
        "answer_text": answer_text,
        "status": turn.status,
    }


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


# ---------------------------------------------------------------------------
# v2 (Low Latency) — Gemini Live session
# ---------------------------------------------------------------------------


@router.get("/{avatar_id}/live-config")
async def live_config(avatar_id: str):
    """Non-secret config for the v2 live UI: voice, system instruction, portrait URL.

    The model name, project, location, and access token are kept server-side —
    the frontend opens a WebSocket to /live, and the backend proxies the
    upstream Vertex AI Gemini Live connection.
    """
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    if avatar.version != "v2":
        raise HTTPException(400, "live-config is only available for v2 avatars")

    # Only attempt to sign if the avatar has an uploaded portrait. v2 avatars
    # using a Gemini Live preset (avatar.preset_name) have no GCS image and
    # don't need one — the frontend renders the bundled preset PNG.
    signed = _sign_avatar(avatar) if avatar.image_gcs_uri else {}
    custom_avatar_url = signed.get("image_signed_url") or None

    return {
        "voice": avatar.voice.value if avatar.voice else None,
        "language": avatar.language or "en-US",
        "system_instruction": avatar_service.build_system_instruction(avatar),
        "custom_avatar_url": custom_avatar_url,
        "preset_name": avatar.preset_name or None,
        "default_greeting": avatar.default_greeting or None,
        "enable_grounding": avatar.enable_grounding,
    }


def _build_setup_frame(avatar: Avatar) -> dict:
    """The first frame sent on the upstream WS — tells Gemini Live what model,
    voice, system instruction, and modalities to use. Built server-side from
    the stored avatar fields so the browser can't tamper with them.

    Mirrors the shape used by ffeldhaus/live-agent's `gemini-live-client.ts`:
    avatarConfig is required, responseModalities is single-mode (VIDEO carries
    audio inside the MP4), and the customizedAvatar takes the portrait inline
    as base64.
    """
    project = _live_project()
    location = _live_location()
    model_path = (
        f"projects/{project}/locations/{location}/publishers/google/models/{LIVE_MODEL}"
    )
    # Voice names in the upstream API are lowercase (e.g. "kore", not "Kore").
    voice_name = (avatar.voice.value if avatar.voice else "Kore").lower()
    audio_only = os.getenv("AVATAR_LIVE_AUDIO_ONLY") == "1"
    # Per-avatar preset_name takes precedence; the env var is just a global
    # fallback for diagnostics or before the create UI was wired up.
    preset_name = avatar.preset_name or os.getenv("AVATAR_LIVE_PRESET_NAME")
    language = avatar.language or "en-US"

    # If the avatar has a default greeting, wedge it into the system
    # instruction so the model speaks it as the first thing on connect.
    # Gemini Live doesn't have a separate "default_greeting" frame slot.
    system_text = avatar_service.build_system_instruction(avatar)
    if avatar.default_greeting:
        system_text = (
            f"{system_text}\n\nOpen the conversation by saying exactly: "
            f'"{avatar.default_greeting.strip()}"'
        )

    setup: dict = {
        "model": model_path,
        "generationConfig": {
            "responseModalities": ["AUDIO"] if audio_only else ["VIDEO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}},
                "languageCode": language,
            },
        },
        "systemInstruction": {"parts": [{"text": system_text}]},
        "outputAudioTranscription": {},
        "inputAudioTranscription": {},
    }
    if avatar.enable_grounding:
        # Mirrors the upstream demo's enableGrounding option — gives the model
        # access to live web facts via Google Search.
        setup["tools"] = [{"googleSearch": {}}]
    if not audio_only:
        if preset_name:
            setup["avatarConfig"] = {"avatarName": preset_name}
        else:
            image_b64, image_mime = _load_avatar_image_b64(avatar)
            setup["avatarConfig"] = {
                "customizedAvatar": {
                    "image_data": image_b64,
                    "image_mime_type": image_mime,
                }
            }
    return {"setup": setup}


def _validate_ws_invite_code(code: Optional[str]) -> bool:
    """Mirror of the HTTP middleware checks for invite-code + master-only access.
    HTTP middleware doesn't run on WebSocket upgrades, so we do it inline."""
    if not code:
        return False
    from routers.auth import validate_code

    result = validate_code(code)
    # Avatars are master-only end-to-end (see MASTER_ONLY_PREFIXES in main.py).
    return bool(result.get("valid") and result.get("is_master"))


async def _relay_client_to_upstream(
    avatar_id: str, client_ws: WebSocket, upstream_ws
) -> None:
    """Forward frames from the browser to Vertex AI verbatim."""
    forwarded = 0
    sniffed_kinds: set[str] = set()
    try:
        while True:
            msg = await client_ws.receive()
            kind = msg.get("type")
            if kind == "websocket.disconnect":
                logger.info(
                    f"[avatar:{avatar_id}] client→upstream: client disconnected "
                    f"after {forwarded} frame(s) kinds={sorted(sniffed_kinds)}"
                )
                return
            text = msg.get("text")
            data = msg.get("bytes")
            if text is not None:
                # Sniff the message kind once so we can confirm the browser
                # really is sending audio chunks / text turns.
                snippet = text[:120]
                for tag in (
                    "realtimeInput",
                    "clientContent",
                    "audio/pcm",
                    "audio/webm",
                    "video/",
                ):
                    if tag in snippet and tag not in sniffed_kinds:
                        sniffed_kinds.add(tag)
                        logger.info(
                            f"[avatar:{avatar_id}] client→upstream first {tag}: "
                            f"{snippet}"
                        )
                await upstream_ws.send(text)
                forwarded += 1
            elif data is not None:
                await upstream_ws.send(data)
                forwarded += 1
    except asyncio.CancelledError:
        logger.info(
            f"[avatar:{avatar_id}] client→upstream: cancelled after "
            f"{forwarded} frame(s) kinds={sorted(sniffed_kinds)}"
        )
        raise
    except WebSocketDisconnect:
        logger.info(
            f"[avatar:{avatar_id}] client→upstream: WebSocketDisconnect "
            f"after {forwarded} frame(s) kinds={sorted(sniffed_kinds)}"
        )
        return
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] client→upstream: unexpected error "
            f"after {forwarded} frame(s): {e}"
        )
        raise


async def _relay_upstream_to_client(
    avatar_id: str, client_ws: WebSocket, upstream_ws
) -> None:
    """Forward frames from Vertex AI to the browser verbatim."""
    forwarded = 0
    text_count = 0
    bytes_count = 0
    setup_complete_seen = False
    try:
        async for msg in upstream_ws:
            if isinstance(msg, (bytes, bytearray)):
                bytes_count += 1
                # Log first 5 frames in detail, then a heartbeat every 25 so
                # we can see whether upstream keeps streaming after a prompt
                # without drowning the logs in MP4 chunk dumps.
                if bytes_count <= 5 or bytes_count % 25 == 0:
                    try:
                        decoded = bytes(msg[:600]).decode("utf-8")
                        preview = decoded
                    except UnicodeDecodeError:
                        preview = "hex:" + bytes(msg[:80]).hex()
                    logger.info(
                        f"[avatar:{avatar_id}] upstream→client[bin#{bytes_count}] "
                        f"({len(msg)} bytes): {preview}"
                    )
                if not setup_complete_seen and len(msg) < 4096:
                    try:
                        decoded = bytes(msg).decode("utf-8")
                        if "setupComplete" in decoded:
                            setup_complete_seen = True
                            logger.info(
                                f"[avatar:{avatar_id}] upstream: setupComplete received "
                                f"(in binary frame)"
                            )
                        elif '"error"' in decoded or '"goAway"' in decoded:
                            logger.warning(
                                f"[avatar:{avatar_id}] upstream sent error/goAway "
                                f"(binary): {decoded[:600]}"
                            )
                    except UnicodeDecodeError:
                        pass
                await client_ws.send_bytes(bytes(msg))
            else:
                text_count += 1
                # Log the first ~10 text frames in full (truncated) so we can
                # see exactly what the upstream is replying with — this is the
                # only way to diagnose silent/empty responses.
                snippet = msg[:600] if isinstance(msg, str) else ""
                if text_count <= 10:
                    logger.info(
                        f"[avatar:{avatar_id}] upstream→client[txt#{text_count}]: "
                        f"{snippet}"
                    )
                if not setup_complete_seen and "setupComplete" in snippet:
                    setup_complete_seen = True
                    logger.info(
                        f"[avatar:{avatar_id}] upstream: setupComplete received"
                    )
                if '"error"' in snippet or '"goAway"' in snippet:
                    logger.warning(
                        f"[avatar:{avatar_id}] upstream sent error/goAway: {snippet}"
                    )
                await client_ws.send_text(msg)
            forwarded += 1
        logger.info(
            f"[avatar:{avatar_id}] upstream→client: stream ended after "
            f"{forwarded} frame(s) (txt={text_count} bin={bytes_count})"
        )
    except asyncio.CancelledError:
        logger.info(
            f"[avatar:{avatar_id}] upstream→client: cancelled after "
            f"{forwarded} frame(s) (txt={text_count} bin={bytes_count})"
        )
        raise
    except Exception as e:
        # websockets.exceptions.ConnectionClosed is the typical exit path
        # when the upstream closes; log at INFO with the close code if we
        # can pull it, otherwise WARNING for unknown failures.
        cls = type(e).__name__
        m = str(e) or repr(e)
        if "ConnectionClosed" in cls:
            logger.info(
                f"[avatar:{avatar_id}] upstream→client: closed by upstream "
                f"after {forwarded} frame(s) (txt={text_count} bin={bytes_count}) "
                f"({cls}: {m})"
            )
        else:
            logger.warning(
                f"[avatar:{avatar_id}] upstream→client: error after "
                f"{forwarded} frame(s) (txt={text_count} bin={bytes_count}) "
                f"({cls}: {m})"
            )
        raise


@router.websocket("/{avatar_id}/live")
async def avatar_live(ws: WebSocket, avatar_id: str):
    """Proxy WebSocket: browser <-> backend <-> Vertex AI Gemini Live.

    The backend mints a service-account access token per session and opens
    the upstream WS using it. Tokens never leave the backend.
    """
    logger.info(f"[avatar:{avatar_id}] live ws upgrade requested")

    invite_code = ws.query_params.get("invite_code")
    if not _validate_ws_invite_code(invite_code):
        logger.warning(
            f"[avatar:{avatar_id}] live ws rejected: invalid/missing invite code"
        )
        await ws.close(code=4401)
        return

    if not deps.firestore_svc:
        logger.error(f"[avatar:{avatar_id}] live ws aborted: firestore_svc unavailable")
        await ws.close(code=1011)
        return

    avatar = deps.firestore_svc.get_avatar(avatar_id)
    if not avatar:
        logger.warning(f"[avatar:{avatar_id}] live ws rejected: avatar not found")
        await ws.close(code=4404)
        return
    if avatar.version != "v2":
        logger.warning(
            f"[avatar:{avatar_id}] live ws rejected: avatar version is "
            f"{avatar.version!r}, expected v2"
        )
        await ws.close(code=4400)
        return

    try:
        token = vertex_access_token()
    except Exception as e:
        logger.exception(f"[avatar:{avatar_id}] token mint failed: {e}")
        await ws.close(code=1011)
        return
    logger.info(f"[avatar:{avatar_id}] minted vertex access token (len={len(token)})")

    location = _live_location()
    host = _live_host(location)
    live_project = _live_project()
    upstream_url_logged = (
        f"wss://{host}/ws/"
        "google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"
    )
    upstream_url = f"{upstream_url_logged}?access_token={token}"
    logger.info(
        f"[avatar:{avatar_id}] live session: project={live_project} "
        f"location={location} host={host} model={LIVE_MODEL} "
        f"voice={avatar.voice.value if avatar.voice else None}"
    )

    try:
        setup_obj = _build_setup_frame(avatar)
        setup_frame = json.dumps(setup_obj)
    except Exception as e:
        logger.exception(f"[avatar:{avatar_id}] setup frame build failed: {e}")
        await ws.close(code=1011)
        return
    # Log a redacted version of the setup frame so we can see model + voice +
    # system instruction without dumping the multi-MB base64 portrait.
    try:
        redacted = json.loads(setup_frame)
        ac = redacted.get("setup", {}).get("avatarConfig", {}).get("customizedAvatar")
        if isinstance(ac, dict) and "image_data" in ac:
            ac["image_data"] = f"<{len(ac['image_data'])} chars redacted>"
        logger.info(f"[avatar:{avatar_id}] setup frame: {json.dumps(redacted)[:1500]}")
    except Exception:
        pass

    # Open upstream BEFORE accepting the client so we can fail fast if Vertex
    # rejects (allowlist or quota). websockets.connect raises on handshake fail.
    import websockets

    logger.info(f"[avatar:{avatar_id}] connecting upstream WS to {upstream_url_logged}")
    # x-goog-user-project tells GCP which project to bill / quota-check this
    # request against. Without it the autopush API check looks at the access
    # token's owning project (random-poc-479104, not allowlisted).
    upstream_headers = {"x-goog-user-project": live_project}
    try:
        upstream_ws = await websockets.connect(
            upstream_url,
            max_size=None,
            additional_headers=upstream_headers,
        )
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] upstream connect failed: {type(e).__name__}: {e}"
        )
        await ws.close(code=1011)
        return
    logger.info(f"[avatar:{avatar_id}] upstream WS connected")

    try:
        await upstream_ws.send(setup_frame)
        logger.info(
            f"[avatar:{avatar_id}] sent setup frame upstream ({len(setup_frame)} bytes)"
        )
        await ws.accept()
        logger.info(f"[avatar:{avatar_id}] client WS accepted; starting relay")
        relay_a = asyncio.create_task(
            _relay_client_to_upstream(avatar_id, ws, upstream_ws)
        )
        relay_b = asyncio.create_task(
            _relay_upstream_to_client(avatar_id, ws, upstream_ws)
        )
        done, pending = await asyncio.wait(
            {relay_a, relay_b}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc:
                logger.warning(
                    f"[avatar:{avatar_id}] relay task ended with "
                    f"{type(exc).__name__}: {exc}"
                )
    except Exception as e:
        logger.exception(f"[avatar:{avatar_id}] live relay error: {e}")
    finally:
        try:
            await upstream_ws.close()
        except Exception:
            pass
        try:
            await ws.close()
        except Exception:
            pass

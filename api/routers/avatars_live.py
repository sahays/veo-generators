"""Avatar v2 (Low Latency) live session — WebSocket proxy to Vertex Gemini Live.

Split out of `routers.avatars` so the CRUD router stays under the project's
file-size budget. Both routers mount under `/api/v1/avatars`.
"""

import asyncio
import base64
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

import deps
import avatar_service
from gcp_auth import vertex_access_token
from helpers import get_or_404, require_firestore
from models import Avatar
from routers.avatars import _sign_avatar  # CRUD lives in avatars.py

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
    return os.getenv("AVATAR_LIVE_LOCATION") or LIVE_LOCATION_DEFAULT


def _live_host(location: str) -> str:
    if location == "global":
        return LIVE_HOST_GLOBAL
    return f"{location}-aiplatform.googleapis.com"


def _live_project() -> str:
    """The GCP project where the Live preview model is allowlisted; distinct
    from GOOGLE_CLOUD_PROJECT (where this Cloud Run service runs)."""
    return os.getenv("AVATAR_LIVE_PROJECT") or LIVE_PROJECT_DEFAULT


def _load_avatar_image_b64(avatar: Avatar) -> tuple[str, str]:
    """Download the avatar's portrait from GCS and return (base64, mime).

    Required for `customizedAvatar` in the live setup frame — the upstream
    API takes the image inline rather than a URL.
    """
    if not deps.storage_svc:
        raise RuntimeError("Storage service unavailable")
    raw = deps.storage_svc.download_bytes(avatar.image_gcs_uri)
    mime = "image/png" if raw[:8].startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    logger.info(
        f"[avatar:{avatar.id}] loaded portrait from {avatar.image_gcs_uri} "
        f"({len(raw)} bytes, mime={mime})"
    )
    return base64.b64encode(raw).decode("ascii"), mime


# ---------------------------------------------------------------------------
# /live-config
# ---------------------------------------------------------------------------


@router.get("/{avatar_id}/live-config")
async def live_config(avatar_id: str):
    """Non-secret config for the v2 live UI: voice, system instruction, portrait URL.

    Model name, project, location, and access token stay server-side — the
    frontend just opens a WebSocket to /live, and the backend proxies the
    upstream Vertex AI Gemini Live connection.
    """
    require_firestore()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    if avatar.version != "v2":
        raise HTTPException(400, "live-config is only available for v2 avatars")

    # Only sign if the avatar has an uploaded portrait. v2 avatars using a
    # Gemini Live preset have no GCS image — frontend renders the bundled PNG.
    signed = _sign_avatar(avatar) if avatar.image_gcs_uri else {}
    return {
        "voice": avatar.voice.value if avatar.voice else None,
        "language": avatar.language or "en-US",
        "system_instruction": avatar_service.build_system_instruction(avatar),
        "custom_avatar_url": signed.get("image_signed_url") or None,
        "preset_name": avatar.preset_name or None,
        "default_greeting": avatar.default_greeting or None,
        "enable_grounding": avatar.enable_grounding,
    }


# ---------------------------------------------------------------------------
# Setup-frame builders
# ---------------------------------------------------------------------------


def _build_speech_config(avatar: Avatar) -> dict:
    voice_name = (avatar.voice.value if avatar.voice else "Kore").lower()
    return {
        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}},
        "languageCode": avatar.language or "en-US",
    }


def _build_avatar_config(avatar: Avatar) -> dict:
    """Choose between a preset avatar (just a name) and a customized portrait
    (uploaded image inlined as base64). Per-avatar `preset_name` wins; the
    AVATAR_LIVE_PRESET_NAME env is a global fallback for diagnostics."""
    preset_name = avatar.preset_name or os.getenv("AVATAR_LIVE_PRESET_NAME")
    if preset_name:
        return {"avatarName": preset_name}
    image_b64, image_mime = _load_avatar_image_b64(avatar)
    return {
        "customizedAvatar": {"image_data": image_b64, "image_mime_type": image_mime},
    }


def _build_system_instruction(avatar: Avatar) -> str:
    """Wedge the default greeting into the system prompt so the model speaks
    it on connect — Gemini Live has no separate `default_greeting` slot."""
    text = avatar_service.build_system_instruction(avatar)
    if avatar.default_greeting:
        text += (
            f'\n\nOpen the conversation by saying exactly: '
            f'"{avatar.default_greeting.strip()}"'
        )
    return text


def _build_setup_frame(avatar: Avatar) -> dict:
    """First frame on the upstream WS — model, voice, system instruction,
    modalities. Built server-side so the browser can't tamper with them."""
    project = _live_project()
    location = _live_location()
    model_path = (
        f"projects/{project}/locations/{location}/publishers/google/models/{LIVE_MODEL}"
    )
    audio_only = os.getenv("AVATAR_LIVE_AUDIO_ONLY") == "1"

    setup: dict = {
        "model": model_path,
        "generationConfig": {
            "responseModalities": ["AUDIO"] if audio_only else ["VIDEO"],
            "speechConfig": _build_speech_config(avatar),
        },
        "systemInstruction": {"parts": [{"text": _build_system_instruction(avatar)}]},
        "outputAudioTranscription": {},
        "inputAudioTranscription": {},
    }
    if avatar.enable_grounding:
        setup["tools"] = [{"googleSearch": {}}]
    if not audio_only:
        setup["avatarConfig"] = _build_avatar_config(avatar)
    return {"setup": setup}


def _validate_ws_invite_code(code: Optional[str]) -> bool:
    """HTTP middleware doesn't run on WebSocket upgrades — repeat its checks
    inline. Avatars are master-only end-to-end (see MASTER_ONLY_PREFIXES)."""
    if not code:
        return False
    from routers.auth import validate_code

    result = validate_code(code)
    return bool(result.get("valid") and result.get("is_master"))


# ---------------------------------------------------------------------------
# WebSocket relay
# ---------------------------------------------------------------------------

CLIENT_SNIFF_TAGS = (
    "realtimeInput",
    "clientContent",
    "audio/pcm",
    "audio/webm",
    "video/",
)


async def _iter_client_frames(client_ws: WebSocket):
    """Yield ('text'|'bytes', payload) from the browser-side WebSocket until
    a disconnect arrives."""
    while True:
        msg = await client_ws.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        text = msg.get("text")
        if text is not None:
            yield "text", text
            continue
        data = msg.get("bytes")
        if data is not None:
            yield "bytes", data


async def _iter_upstream_frames(upstream_ws):
    """Yield ('text'|'bytes', payload) from the Vertex AI WebSocket."""
    async for msg in upstream_ws:
        if isinstance(msg, (bytes, bytearray)):
            yield "bytes", bytes(msg)
        else:
            yield "text", msg


def _bin_preview(payload: bytes) -> str:
    try:
        return bytes(payload[:600]).decode("utf-8")
    except UnicodeDecodeError:
        return "hex:" + bytes(payload[:80]).hex()


def _sniff_client_text(avatar_id: str, snippet: str, sniffed: set[str]) -> None:
    for tag in CLIENT_SNIFF_TAGS:
        if tag in snippet and tag not in sniffed:
            sniffed.add(tag)
            logger.info(
                f"[avatar:{avatar_id}] client→upstream first {tag}: {snippet}"
            )


def _log_upstream_text(
    avatar_id: str, text_count: int, snippet: str, setup_complete_seen: bool
) -> bool:
    if text_count <= 10:
        logger.info(
            f"[avatar:{avatar_id}] upstream→client[txt#{text_count}]: {snippet}"
        )
    if not setup_complete_seen and "setupComplete" in snippet:
        logger.info(f"[avatar:{avatar_id}] upstream: setupComplete received")
        setup_complete_seen = True
    if '"error"' in snippet or '"goAway"' in snippet:
        logger.warning(f"[avatar:{avatar_id}] upstream sent error/goAway: {snippet}")
    return setup_complete_seen


def _log_upstream_bytes(
    avatar_id: str, bytes_count: int, payload: bytes, setup_complete_seen: bool
) -> bool:
    if bytes_count <= 5 or bytes_count % 25 == 0:
        logger.info(
            f"[avatar:{avatar_id}] upstream→client[bin#{bytes_count}] "
            f"({len(payload)} bytes): {_bin_preview(payload)}"
        )
    if setup_complete_seen or len(payload) >= 4096:
        return setup_complete_seen
    try:
        decoded = bytes(payload).decode("utf-8")
    except UnicodeDecodeError:
        return setup_complete_seen
    if "setupComplete" in decoded:
        logger.info(
            f"[avatar:{avatar_id}] upstream: setupComplete received (in binary frame)"
        )
        return True
    if '"error"' in decoded or '"goAway"' in decoded:
        logger.warning(
            f"[avatar:{avatar_id}] upstream sent error/goAway (binary): {decoded[:600]}"
        )
    return setup_complete_seen


async def _relay_client_to_upstream(
    avatar_id: str, client_ws: WebSocket, upstream_ws
) -> None:
    """Forward frames from the browser to Vertex AI verbatim."""
    forwarded = 0
    sniffed: set[str] = set()
    tail = lambda: f"after {forwarded} frame(s) kinds={sorted(sniffed)}"  # noqa: E731
    try:
        async for kind, payload in _iter_client_frames(client_ws):
            if kind == "text":
                _sniff_client_text(avatar_id, payload[:120], sniffed)
            await upstream_ws.send(payload)
            forwarded += 1
        logger.info(f"[avatar:{avatar_id}] client→upstream: client disconnected {tail()}")
    except asyncio.CancelledError:
        logger.info(f"[avatar:{avatar_id}] client→upstream: cancelled {tail()}")
        raise
    except WebSocketDisconnect:
        logger.info(f"[avatar:{avatar_id}] client→upstream: WebSocketDisconnect {tail()}")
        return
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] client→upstream: unexpected error {tail()}: {e}"
        )
        raise


async def _relay_upstream_to_client(
    avatar_id: str, client_ws: WebSocket, upstream_ws
) -> None:
    """Forward frames from Vertex AI to the browser verbatim."""
    text_count = bytes_count = 0
    setup_complete_seen = False
    tail = lambda: (  # noqa: E731
        f"after {text_count + bytes_count} frame(s) "
        f"(txt={text_count} bin={bytes_count})"
    )
    try:
        async for kind, payload in _iter_upstream_frames(upstream_ws):
            if kind == "bytes":
                bytes_count += 1
                setup_complete_seen = _log_upstream_bytes(
                    avatar_id, bytes_count, payload, setup_complete_seen
                )
                await client_ws.send_bytes(payload)
            else:
                text_count += 1
                setup_complete_seen = _log_upstream_text(
                    avatar_id, text_count, payload[:600], setup_complete_seen
                )
                await client_ws.send_text(payload)
        logger.info(f"[avatar:{avatar_id}] upstream→client: stream ended {tail()}")
    except asyncio.CancelledError:
        logger.info(f"[avatar:{avatar_id}] upstream→client: cancelled {tail()}")
        raise
    except Exception as e:
        cls = type(e).__name__
        msg = str(e) or repr(e)
        level = logger.info if "ConnectionClosed" in cls else logger.warning
        level(
            f"[avatar:{avatar_id}] upstream→client: "
            f"{'closed by upstream' if 'ConnectionClosed' in cls else 'error'} "
            f"{tail()} ({cls}: {msg})"
        )
        raise


# ---------------------------------------------------------------------------
# /live WebSocket
# ---------------------------------------------------------------------------


def _log_setup_frame(avatar_id: str, setup_frame: str) -> None:
    """Log the setup frame with the multi-MB base64 portrait redacted."""
    try:
        redacted = json.loads(setup_frame)
        ac = redacted.get("setup", {}).get("avatarConfig", {}).get("customizedAvatar")
        if isinstance(ac, dict) and "image_data" in ac:
            ac["image_data"] = f"<{len(ac['image_data'])} chars redacted>"
        logger.info(f"[avatar:{avatar_id}] setup frame: {json.dumps(redacted)[:1500]}")
    except Exception:
        pass


async def _open_upstream(avatar_id: str, token: str):
    """Open the Vertex AI Live WS. Returns (upstream_ws, project) or None on
    failure (we close the client with code 1011 in that case)."""
    location = _live_location()
    host = _live_host(location)
    live_project = _live_project()
    url_logged = (
        f"wss://{host}/ws/"
        "google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"
    )
    logger.info(
        f"[avatar:{avatar_id}] live session: project={live_project} "
        f"location={location} host={host} model={LIVE_MODEL}"
    )
    logger.info(f"[avatar:{avatar_id}] connecting upstream WS to {url_logged}")
    # x-goog-user-project tells GCP which project to bill / quota-check this
    # request against. Without it the autopush API check looks at the access
    # token's owning project (random-poc-479104, not allowlisted).
    import websockets

    return await websockets.connect(
        f"{url_logged}?access_token={token}",
        max_size=None,
        additional_headers={"x-goog-user-project": live_project},
    )


async def _run_relay(avatar_id: str, ws: WebSocket, upstream_ws) -> None:
    """Race the two relay directions; whichever finishes first cancels the other."""
    relay_a = asyncio.create_task(_relay_client_to_upstream(avatar_id, ws, upstream_ws))
    relay_b = asyncio.create_task(_relay_upstream_to_client(avatar_id, ws, upstream_ws))
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


@router.websocket("/{avatar_id}/live")
async def avatar_live(ws: WebSocket, avatar_id: str):
    """Proxy WebSocket: browser <-> backend <-> Vertex AI Gemini Live.

    The backend mints a service-account access token per session and opens
    the upstream WS using it. Tokens never leave the backend.
    """
    logger.info(f"[avatar:{avatar_id}] live ws upgrade requested")

    if not _validate_ws_invite_code(ws.query_params.get("invite_code")):
        logger.warning(f"[avatar:{avatar_id}] live ws rejected: invalid/missing invite code")
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

    try:
        setup_frame = json.dumps(_build_setup_frame(avatar))
    except Exception as e:
        logger.exception(f"[avatar:{avatar_id}] setup frame build failed: {e}")
        await ws.close(code=1011)
        return
    _log_setup_frame(avatar_id, setup_frame)

    try:
        upstream_ws = await _open_upstream(avatar_id, token)
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
        await _run_relay(avatar_id, ws, upstream_ws)
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

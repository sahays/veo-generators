"""Avatar v2 (Low Latency) live session — WebSocket proxy to Vertex Gemini Live.

Split out of `routers.avatars` so the CRUD router stays under the project's
file-size budget. Both routers mount under `/api/v1/avatars`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

import avatar_service
import deps
from gcp_auth import vertex_access_token
from helpers import ensure_services_ready, get_or_404
from models import Avatar
from routers.studio._avatars_live_helpers import (  # noqa: F401
    CLIENT_SNIFF_TAGS,
    _bin_preview,
    _close_both_websockets,
    _iter_client_frames,
    _iter_upstream_frames,
    _live_log,
    _log_setup_frame,
    _log_upstream_bytes,
    _log_upstream_relay_exception,
    _log_upstream_text,
    _sniff_client_text,
)
from routers.studio.avatars import _sign_avatar

LIVE_MODEL = os.getenv("AVATAR_LIVE_MODEL", "gemini-3.8-live")
LIVE_LOCATION_DEFAULT = "us"
LIVE_HOST_GLOBAL = "aiplatform.googleapis.com"
LIVE_MULTI_REGIONAL_LOCATIONS = {"us", "eu"}
LIVE_PROJECT_DEFAULT = "aug18-25-3"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/avatars", tags=["avatars"])


def _live_location() -> str:
    """Return configured Vertex AI Live location."""
    return os.getenv("AVATAR_LIVE_LOCATION") or LIVE_LOCATION_DEFAULT


def _live_host(location: str) -> str:
    """Resolve regional or multi-regional Vertex AI WebSocket hostname."""
    if location == "global":
        return LIVE_HOST_GLOBAL
    if location in LIVE_MULTI_REGIONAL_LOCATIONS:
        return f"aiplatform.{location}.rep.googleapis.com"
    return f"{location}-aiplatform.googleapis.com"


def _live_project() -> str:
    """The GCP project where the Live model runs."""
    return (
        os.getenv("AVATAR_LIVE_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or LIVE_PROJECT_DEFAULT
    )


def _load_avatar_image_b64(avatar: Avatar) -> tuple[str, str]:
    """Download the avatar's portrait from GCS and return (base64, mime)."""
    if not deps.storage_svc:
        raise RuntimeError("Storage service unavailable")
    raw = deps.storage_svc.download_bytes(avatar.image_gcs_uri)
    mime = "image/png" if raw[:8].startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
    logger.info(
        f"[avatar:{avatar.id}] loaded portrait from {avatar.image_gcs_uri} ({len(raw)} bytes, mime={mime})",
        extra=_live_log(
            "_load_avatar_image_b64",
            "portrait_loaded",
            f"bytes={len(raw)}",
            "gcs_download",
        ),
    )
    return base64.b64encode(raw).decode("ascii"), mime


@router.get("/{avatar_id}/live-config")
async def live_config(avatar_id: str) -> dict[str, Any]:
    """Non-secret config for the v2 live UI: voice, system instruction, portrait URL."""
    ensure_services_ready()
    avatar = get_or_404(deps.firestore_svc.get_avatar, avatar_id, "Avatar")
    if avatar.version != "v2":
        raise HTTPException(400, "live-config is only available for v2 avatars")
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


def _build_speech_config(avatar: Avatar) -> dict[str, Any]:
    """Build speechConfig dictionary for Vertex AI Gemini Live."""
    voice_name = (avatar.voice.value if avatar.voice else "Kore").lower()
    return {
        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}},
        "languageCode": avatar.language or "en-US",
    }


def _build_avatar_config(avatar: Avatar) -> dict[str, Any]:
    """Choose between a preset avatar and a customized base64 portrait."""
    preset_name = avatar.preset_name or os.getenv("AVATAR_LIVE_PRESET_NAME")
    if preset_name:
        return {"avatarName": preset_name}
    image_b64, image_mime = _load_avatar_image_b64(avatar)
    return {
        "customizedAvatar": {"image_data": image_b64, "image_mime_type": image_mime}
    }


def _build_system_instruction(avatar: Avatar) -> str:
    """Wedge the default greeting into the system prompt."""
    text = avatar_service.build_system_instruction(avatar)
    if avatar.default_greeting:
        text += f'\n\nOpen the conversation by saying exactly: "{avatar.default_greeting.strip()}"'
    return text


def _build_setup_frame(avatar: Avatar) -> dict[str, Any]:
    """First frame on the upstream WS — model, voice, system instruction, modalities."""
    project = _live_project()
    location = _live_location()
    model_path = (
        f"projects/{project}/locations/{location}/publishers/google/models/{LIVE_MODEL}"
    )
    audio_only = os.getenv("AVATAR_LIVE_AUDIO_ONLY") == "1"
    setup: dict[str, Any] = {
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
    """Validate invite code for WebSocket upgrade (master and power users only)."""
    if not code:
        return False
    from routers.auth import validate_code

    result = validate_code(code)
    return bool(
        result.get("valid") and (result.get("is_master") or result.get("is_power"))
    )


async def _relay_client_to_upstream(
    avatar_id: str, client_ws: WebSocket, upstream_ws: Any
) -> None:
    """Forward frames from the browser to Vertex AI verbatim."""
    forwarded = 0
    sniffed: set[str] = set()
    try:
        async for kind, payload in _iter_client_frames(client_ws):
            if kind == "text":
                _sniff_client_text(avatar_id, payload[:120], sniffed)
            await upstream_ws.send(payload)
            forwarded += 1
        logger.info(
            f"[avatar:{avatar_id}] client->upstream: disconnected after {forwarded} frame(s)",
            extra=_live_log(
                "_relay_client_to_upstream",
                "client_disconnected",
                f"frames={forwarded}",
            ),
        )
    except asyncio.CancelledError:
        logger.info(
            f"[avatar:{avatar_id}] client->upstream: cancelled after {forwarded} frame(s)",
            extra=_live_log(
                "_relay_client_to_upstream", "relay_cancelled", f"frames={forwarded}"
            ),
        )
        raise
    except WebSocketDisconnect:
        logger.info(
            f"[avatar:{avatar_id}] client->upstream: WebSocketDisconnect after {forwarded} frame(s)",
            extra=_live_log(
                "_relay_client_to_upstream", "ws_disconnect", f"frames={forwarded}"
            ),
        )
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] client->upstream: unexpected error: {e}",
            extra=_live_log("_relay_client_to_upstream", "unexpected_error", str(e)),
        )
        raise


async def _relay_upstream_to_client(
    avatar_id: str, client_ws: WebSocket, upstream_ws: Any
) -> None:
    """Forward frames from Vertex AI to the browser verbatim."""
    text_count = bytes_count = 0
    setup_seen = False
    try:
        async for kind, payload in _iter_upstream_frames(upstream_ws):
            if kind == "bytes":
                bytes_count += 1
                setup_seen = _log_upstream_bytes(
                    avatar_id, bytes_count, payload, setup_seen
                )
                await client_ws.send_bytes(payload)
            else:
                text_count += 1
                setup_seen = _log_upstream_text(
                    avatar_id, text_count, payload[:600], setup_seen
                )
                await client_ws.send_text(payload)
        logger.info(
            f"[avatar:{avatar_id}] upstream->client: stream ended (txt={text_count} bin={bytes_count})",
            extra=_live_log(
                "_relay_upstream_to_client",
                "stream_ended",
                f"txt={text_count},bin={bytes_count}",
            ),
        )
    except asyncio.CancelledError:
        logger.info(
            f"[avatar:{avatar_id}] upstream->client: cancelled",
            extra=_live_log("_relay_upstream_to_client", "cancelled", avatar_id),
        )
        raise
    except Exception as e:
        _log_upstream_relay_exception(avatar_id, e, text_count + bytes_count)
        raise


async def _open_upstream(avatar_id: str, token: str) -> Any:
    """Open the Vertex AI Live WebSocket connection."""
    location = _live_location()
    host = _live_host(location)
    live_project = _live_project()
    url_logged = f"wss://{host}/ws/google.cloud.aiplatform.v1beta1.LlmBidiService/BidiGenerateContent"
    logger.info(
        f"[avatar:{avatar_id}] live session: project={live_project} location={location} host={host} model={LIVE_MODEL}",
        extra=_live_log(
            "_open_upstream", "live_session_params", f"project={live_project}"
        ),
    )
    logger.info(
        f"[avatar:{avatar_id}] connecting upstream WS to {url_logged}",
        extra=_live_log("_open_upstream", "connecting_upstream", host),
    )
    import websockets

    return await websockets.connect(
        f"{url_logged}?access_token={token}",
        max_size=None,
        additional_headers={
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": live_project,
        },
    )


async def _run_relay(avatar_id: str, ws: WebSocket, upstream_ws: Any) -> None:
    """Race the two relay directions; whichever finishes first cancels the other."""
    relay_a = asyncio.create_task(_relay_client_to_upstream(avatar_id, ws, upstream_ws))
    relay_b = asyncio.create_task(_relay_upstream_to_client(avatar_id, ws, upstream_ws))
    done, pending = await asyncio.wait(
        {relay_a, relay_b}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    for t in done:
        try:
            await t
        except Exception as exc:
            logger.warning(
                f"[avatar:{avatar_id}] relay task ended with {type(exc).__name__}: {exc}",
                extra=_live_log("_run_relay", "relay_task_exception", str(exc)),
            )


async def _verify_live_ws_preconditions(ws: WebSocket, avatar_id: str) -> Avatar | None:
    """Validate invite code, Firestore service, and v2 avatar existence on WS connect."""
    if not _validate_ws_invite_code(ws.query_params.get("invite_code")):
        logger.warning(
            f"[avatar:{avatar_id}] live ws rejected: invalid invite code",
            extra=_live_log("avatar_live", "invalid_invite", avatar_id),
        )
        await ws.close(code=4401)
        return None
    if not deps.firestore_svc:
        logger.error(
            f"[avatar:{avatar_id}] live ws aborted: firestore_svc unavailable",
            extra=_live_log("avatar_live", "no_firestore", avatar_id),
        )
        await ws.close(code=1011)
        return None
    avatar = deps.firestore_svc.get_avatar(avatar_id)
    if not avatar:
        logger.warning(
            f"[avatar:{avatar_id}] live ws rejected: avatar not found",
            extra=_live_log("avatar_live", "avatar_not_found", avatar_id),
        )
        await ws.close(code=4404)
        return None
    if avatar.version != "v2":
        logger.warning(
            f"[avatar:{avatar_id}] live ws rejected: version={avatar.version!r}",
            extra=_live_log("avatar_live", "wrong_version", avatar.version),
        )
        await ws.close(code=4400)
        return None
    return avatar


async def _prepare_upstream_session(
    ws: WebSocket, avatar_id: str, avatar: Avatar
) -> tuple[Any, str] | None:
    """Mint Vertex token, build setup frame, and connect upstream WebSocket."""
    try:
        token = vertex_access_token()
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] token mint failed: {e}",
            extra=_live_log("avatar_live", "token_mint_failed", str(e)),
        )
        await ws.close(code=1011)
        return None
    try:
        setup_frame = json.dumps(_build_setup_frame(avatar))
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] setup frame build failed: {e}",
            extra=_live_log("avatar_live", "setup_build_failed", str(e)),
        )
        await ws.close(code=1011)
        return None
    _log_setup_frame(avatar_id, setup_frame)
    try:
        upstream_ws = await _open_upstream(avatar_id, token)
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] upstream connect failed: {e}",
            extra=_live_log("avatar_live", "upstream_connect_failed", str(e)),
        )
        await ws.close(code=1011)
        return None
    return upstream_ws, setup_frame


@router.websocket("/{avatar_id}/live")
async def avatar_live(ws: WebSocket, avatar_id: str) -> None:
    """Proxy WebSocket: browser <-> backend <-> Vertex AI Gemini Live."""
    logger.info(
        f"[avatar:{avatar_id}] live ws upgrade requested",
        extra=_live_log("avatar_live", "upgrade_requested", avatar_id),
    )
    avatar = await _verify_live_ws_preconditions(ws, avatar_id)
    if not avatar:
        return
    session = await _prepare_upstream_session(ws, avatar_id, avatar)
    if not session:
        return
    upstream_ws, setup_frame = session
    logger.info(
        f"[avatar:{avatar_id}] upstream WS connected",
        extra=_live_log("avatar_live", "upstream_connected", avatar_id),
    )
    try:
        await upstream_ws.send(setup_frame)
        await ws.accept()
        logger.info(
            f"[avatar:{avatar_id}] client WS accepted; starting relay",
            extra=_live_log("avatar_live", "relay_started", avatar_id),
        )
        await _run_relay(avatar_id, ws, upstream_ws)
    except Exception as e:
        logger.exception(
            f"[avatar:{avatar_id}] live relay error: {e}",
            extra=_live_log("avatar_live", "live_relay_error", str(e)),
        )
    finally:
        await _close_both_websockets(ws, upstream_ws)

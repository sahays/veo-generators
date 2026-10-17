"""WebSocket frame iteration, binary preview, and structured logging helpers for Avatar Live."""

from __future__ import annotations

from collections.abc import AsyncIterator
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CLIENT_SNIFF_TAGS = (
    "realtimeInput",
    "clientContent",
    "audio/pcm",
    "audio/webm",
    "video/",
)


def _live_log(where: str, what: str, why: str, how: str = "ws_relay") -> dict[str, str]:
    """Build structured 5W1H telemetry context for avatar live sessions."""
    return {
        "who": "avatars_live_router",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


async def _iter_client_frames(client_ws: WebSocket) -> AsyncIterator[tuple[str, Any]]:
    """Yield ('text'|'bytes', payload) from the browser-side WebSocket."""
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


async def _iter_upstream_frames(upstream_ws: Any) -> AsyncIterator[tuple[str, Any]]:
    """Yield ('text'|'bytes', payload) from the Vertex AI WebSocket."""
    async for msg in upstream_ws:
        if isinstance(msg, (bytes, bytearray)):
            yield "bytes", bytes(msg)
        else:
            yield "text", msg


def _bin_preview(payload: bytes) -> str:
    """Format binary frame preview as UTF-8 snippet or hex prefix."""
    try:
        return bytes(payload[:600]).decode("utf-8")
    except UnicodeDecodeError:
        return "hex:" + bytes(payload[:80]).hex()


def _sniff_client_text(avatar_id: str, snippet: str, sniffed: set[str]) -> None:
    """Log the first occurrence of each client frame tag."""
    for tag in CLIENT_SNIFF_TAGS:
        if tag in snippet and tag not in sniffed:
            sniffed.add(tag)
            logger.info(
                f"[avatar:{avatar_id}] client->upstream first {tag}: {snippet}",
                extra=_live_log("_sniff_client_text", f"first_{tag}", avatar_id),
            )


def _log_upstream_text(
    avatar_id: str, text_count: int, snippet: str, setup_complete_seen: bool
) -> bool:
    """Log text frames received from upstream Vertex AI WebSocket."""
    if text_count <= 10:
        logger.info(
            f"[avatar:{avatar_id}] upstream->client[txt#{text_count}]: {snippet}",
            extra=_live_log(
                "_log_upstream_text", "upstream_txt", f"count={text_count}"
            ),
        )
    if not setup_complete_seen and "setupComplete" in snippet:
        logger.info(
            f"[avatar:{avatar_id}] upstream: setupComplete received",
            extra=_live_log("_log_upstream_text", "setup_complete", avatar_id),
        )
        setup_complete_seen = True
    if '"error"' in snippet or '"goAway"' in snippet:
        logger.warning(
            f"[avatar:{avatar_id}] upstream sent error/goAway: {snippet}",
            extra=_live_log(
                "_log_upstream_text", "upstream_error_or_goaway", snippet[:120]
            ),
        )
    return setup_complete_seen


def _log_upstream_bytes(
    avatar_id: str, bytes_count: int, payload: bytes, setup_complete_seen: bool
) -> bool:
    """Log binary frames received from upstream Vertex AI WebSocket."""
    if bytes_count <= 5 or bytes_count % 25 == 0:
        logger.info(
            f"[avatar:{avatar_id}] upstream->client[bin#{bytes_count}] ({len(payload)} bytes): {_bin_preview(payload)}",
            extra=_live_log(
                "_log_upstream_bytes", "upstream_bin", f"count={bytes_count}"
            ),
        )
    if setup_complete_seen or len(payload) >= 4096:
        return setup_complete_seen
    try:
        decoded = bytes(payload).decode("utf-8")
    except UnicodeDecodeError:
        return setup_complete_seen
    if "setupComplete" in decoded:
        logger.info(
            f"[avatar:{avatar_id}] upstream: setupComplete received (in binary frame)",
            extra=_live_log("_log_upstream_bytes", "setup_complete_bin", avatar_id),
        )
        return True
    if '"error"' in decoded or '"goAway"' in decoded:
        logger.warning(
            f"[avatar:{avatar_id}] upstream sent error/goAway (binary): {decoded[:600]}",
            extra=_live_log("_log_upstream_bytes", "upstream_bin_error", decoded[:120]),
        )
    return setup_complete_seen


def _log_upstream_relay_exception(
    avatar_id: str, e: Exception, total_frames: int
) -> None:
    """Log termination or unexpected error on upstream->client relay."""
    cls = type(e).__name__
    msg = str(e) or repr(e)
    ctx = _live_log("_relay_upstream_to_client", cls, f"frames={total_frames}")
    if "ConnectionClosed" in cls:
        logger.info(
            f"[avatar:{avatar_id}] upstream->client closed ({cls}: {msg})", extra=ctx
        )
    else:
        logger.warning(
            f"[avatar:{avatar_id}] upstream->client error ({cls}: {msg})", extra=ctx
        )


def _log_setup_frame(avatar_id: str, setup_frame: str) -> None:
    """Log the setup frame with the multi-MB base64 portrait redacted."""
    try:
        redacted = json.loads(setup_frame)
        ac = redacted.get("setup", {}).get("avatarConfig", {}).get("customizedAvatar")
        if isinstance(ac, dict) and "image_data" in ac:
            ac["image_data"] = f"<{len(ac['image_data'])} chars redacted>"
        logger.info(
            f"[avatar:{avatar_id}] setup frame: {json.dumps(redacted)[:1500]}",
            extra=_live_log("_log_setup_frame", "setup_frame_built", avatar_id),
        )
    except Exception:
        pass


async def _close_both_websockets(ws: WebSocket, upstream_ws: Any) -> None:
    """Best-effort close of both upstream and client WebSockets."""
    for sock in (upstream_ws, ws):
        try:
            await sock.close()
        except Exception:
            pass

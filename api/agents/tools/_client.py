"""Shared HTTPX client used by every agent tool.

Supports two execution modes for strict separation of duties:
1. Remote Microservice Mode (`VEOGEN_API_ORIGIN` set, e.g. `https://veo-generators-...run.app`):
   The dedicated `veo-generators-agents` Cloud Run service calls the main API over HTTPS.
2. In-Process ASGI Mode (`VEOGEN_API_ORIGIN` unset):
   Reaches the FastAPI app through an in-process ASGITransport during unit tests or local dev.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "http://internal"
_TIMEOUT = 30.0

_client: Optional[httpx.AsyncClient] = None
_client_origin: Optional[str] = None


def _get_client() -> httpx.AsyncClient:
    global _client, _client_origin
    api_origin = os.getenv("VEOGEN_API_ORIGIN", "").strip().rstrip("/")
    if _client is None or _client_origin != api_origin:
        if api_origin:
            _client = httpx.AsyncClient(
                base_url=api_origin,
                timeout=_TIMEOUT,
            )
        else:
            # Lazy import to break circular dep in local/test mode
            from main import app

            _client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=BASE_URL,
                timeout=_TIMEOUT,
            )
        _client_origin = api_origin
    return _client


async def close_client() -> None:
    """Close the shared AsyncClient. Called from FastAPI shutdown."""
    global _client, _client_origin
    if _client is not None:
        await _client.aclose()
        _client = None
        _client_origin = None


async def api_call(
    method: str,
    path: str,
    invite_code: str,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Make an authenticated REST API call to the VeoGen backend."""
    headers = {"X-Invite-Code": invite_code, "User-Agent": "VeoAgent/2.0"}
    client = _get_client()
    response = await client.request(
        method, path, headers=headers, json=json, params=params, follow_redirects=True
    )
    if response.status_code >= 400:
        logger.error(
            "API Error %s on %s: %s",
            response.status_code,
            path,
            response.text,
            extra={
                "who": "agent_client",
                "where": "api_call",
                "what": f"API error {response.status_code} on {path}",
                "why": response.text[:200],
                "how": method,
            },
        )
        detail: Any = response.text
        try:
            detail = response.json()
        except Exception:
            pass
        return {"error": f"API returned {response.status_code}", "detail": detail}
    try:
        return response.json()
    except Exception:
        return {"error": "Non-JSON response", "detail": response.text}


async def list_recent(endpoint: str, invite_code: str, limit: int = 5) -> List[dict]:
    """Fetch all records and return the most recent `limit`."""
    result = await api_call("GET", endpoint, invite_code)
    return result[:limit] if isinstance(result, list) else []


async def create_job(endpoint: str, invite_code: str, payload: dict) -> dict:
    return await api_call("POST", endpoint, invite_code, json=payload)

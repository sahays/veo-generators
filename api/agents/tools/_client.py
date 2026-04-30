"""Shared HTTPX client used by every agent tool.

All tools reach the FastAPI app through an in-process ASGITransport so we
don't pay the cost of a real network round-trip. The client is a module-level
singleton; FastAPI's shutdown hook closes it via `close_client()`.
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "http://internal"
_TIMEOUT = 30.0

_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # Lazy import to break circular dep (tools → main → routers → agents → tools).
        from main import app

        _client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
            timeout=_TIMEOUT,
        )
    return _client


async def close_client() -> None:
    """Close the shared AsyncClient. Called from FastAPI shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def api_call(
    method: str,
    path: str,
    invite_code: str,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Any:
    """Make an authenticated API call through the in-process FastAPI app."""
    headers = {"X-Invite-Code": invite_code, "User-Agent": "VeoAgent/1.0"}
    client = _get_client()
    response = await client.request(
        method, path, headers=headers, json=json, params=params, follow_redirects=True
    )
    if response.status_code >= 400:
        logger.error(
            "API Error %s on %s: %s", response.status_code, path, response.text
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

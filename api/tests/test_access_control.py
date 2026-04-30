"""Tests for the role-based write gate in api/main.py.

Verifies that:
- Master users can hit any endpoint.
- Guests (valid non-master code) can hit GETs and the allowlisted POSTs.
- Guests are blocked from any other write method with HTTP 403.
- Aanya (POST /api/v1/chat) is blocked for guests.
"""

import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MASTER_CODE = "test-master-code"
GUEST_CODE = "test-guest-code"

os.environ["MASTER_INVITE_CODE"] = MASTER_CODE


@pytest.fixture
def client(monkeypatch):
    """TestClient over the real app, with firestore mocked to recognize GUEST_CODE."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models_infra import InviteCode

    guest_invite = InviteCode(
        id="inv-guest",
        code=GUEST_CODE,
        label="guest",
        is_active=True,
        daily_credits=1000,
        expires_at=None,
        createdAt=datetime.now(timezone.utc),
    )

    fake_firestore = MagicMock()
    fake_firestore.get_invite_code_by_value = MagicMock(
        side_effect=lambda code: guest_invite if code == GUEST_CODE else None
    )
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    return TestClient(app)


def _master_headers():
    return {"X-Invite-Code": MASTER_CODE}


def _guest_headers():
    return {"X-Invite-Code": GUEST_CODE}


class TestGuestBlockedFromWrites:
    def test_post_productions_blocked_for_guest(self, client):
        res = client.post(
            "/api/v1/productions", headers=_guest_headers(), json={"name": "x"}
        )
        assert res.status_code == 403
        assert "Master access required" in res.json()["detail"]

    def test_patch_blocked_for_guest(self, client):
        res = client.patch(
            "/api/v1/productions/abc/scenes/1",
            headers=_guest_headers(),
            json={},
        )
        assert res.status_code == 403

    def test_delete_blocked_for_guest(self, client):
        res = client.delete("/api/v1/uploads/some-id", headers=_guest_headers())
        assert res.status_code == 403

    def test_chat_blocked_for_guest(self, client):
        res = client.post(
            "/api/v1/chat", headers=_guest_headers(), json={"message": "hi"}
        )
        assert res.status_code == 403


class TestAllowlistedPostsAllowedForGuest:
    def test_auth_validate_allowed(self, client):
        res = client.post(
            "/api/v1/auth/validate",
            headers=_guest_headers(),
            json={"code": GUEST_CODE},
        )
        # Validate is allowlisted — middleware lets it through; handler returns 200.
        assert res.status_code != 403

    def test_pricing_estimate_allowed(self, client):
        res = client.post(
            "/api/v1/pricing/estimate",
            headers=_guest_headers(),
            json={"feature": "production", "scene_count": 1, "video_length_seconds": 8},
        )
        # May be 200 or a validation error from the handler, but never 403.
        assert res.status_code != 403


class TestGuestCanRead:
    def test_get_endpoint_not_blocked_by_middleware(self, client):
        # GETs should never hit the master-required gate.
        res = client.get("/api/v1/productions", headers=_guest_headers())
        assert res.status_code != 403


class TestMasterCanWrite:
    def test_master_post_passes_middleware(self, client):
        # Master code passes the gate; downstream may 4xx/5xx on missing deps,
        # but it must not be the middleware's 403.
        res = client.post(
            "/api/v1/productions", headers=_master_headers(), json={"name": "x"}
        )
        assert res.status_code != 403


class TestMissingCode:
    def test_missing_invite_code_is_401(self, client):
        res = client.post("/api/v1/productions", json={"name": "x"})
        assert res.status_code == 401

    def test_invalid_invite_code_is_401(self, client):
        res = client.post(
            "/api/v1/productions",
            headers={"X-Invite-Code": "bogus"},
            json={"name": "x"},
        )
        assert res.status_code == 401

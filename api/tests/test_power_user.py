"""Tests for the power-user feature: promote/demote endpoints and the
WebSocket privilege check.

Complements test_access_control.py (which covers the HTTP middleware gate) by
exercising the actual mutation behavior of promotion/demotion and the live
avatar WS validator.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MASTER_CODE = "test-master-code"
POWER_CODE = "test-power-code"

os.environ["MASTER_INVITE_CODE"] = MASTER_CODE


def _master_headers():
    return {"X-Invite-Code": MASTER_CODE}


@pytest.fixture
def client_and_store(monkeypatch):
    """TestClient with firestore mocked so get_invite_code returns a known
    record and update_invite_code can be inspected."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models_infra import InviteCode

    target = InviteCode(id="inv-1", code="abc", is_active=True, is_power=False)

    fake_firestore = MagicMock()
    fake_firestore.get_invite_code = MagicMock(return_value=target)
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    return TestClient(app), fake_firestore


class TestPromote:
    def test_promote_sets_power_and_default_14_day_expiry(self, client_and_store):
        client, fake = client_and_store
        res = client.post("/api/v1/auth/codes/inv-1/promote", headers=_master_headers())
        assert res.status_code == 200

        code_id, updates = fake.update_invite_code.call_args[0]
        assert code_id == "inv-1"
        assert updates["is_power"] is True
        assert updates["is_active"] is True
        # Expiry should land ~14 days out (POWER_DEFAULT_DAYS).
        delta = updates["expires_at"] - datetime.now(timezone.utc)
        assert timedelta(days=13) < delta <= timedelta(days=14)

    def test_promote_unknown_code_is_404(self, client_and_store):
        client, fake = client_and_store
        fake.get_invite_code = MagicMock(return_value=None)
        res = client.post(
            "/api/v1/auth/codes/missing/promote", headers=_master_headers()
        )
        assert res.status_code == 404

    def test_promote_requires_a_code(self, client_and_store):
        client, _ = client_and_store
        # No invite code at all → middleware rejects with 401 before the router.
        res = client.post("/api/v1/auth/codes/inv-1/promote")
        assert res.status_code == 401


class TestDemote:
    def test_demote_clears_power_only(self, client_and_store):
        client, fake = client_and_store
        res = client.post("/api/v1/auth/codes/inv-1/demote", headers=_master_headers())
        assert res.status_code == 200

        code_id, updates = fake.update_invite_code.call_args[0]
        assert code_id == "inv-1"
        # Demotion leaves activity/expiry untouched — only power is revoked.
        assert updates == {"is_power": False}


class TestWebSocketPrivilegeCheck:
    def test_ws_validator_allows_master_and_power_only(self, monkeypatch):
        import deps
        from models_infra import InviteCode
        from routers.avatars_live import _validate_ws_invite_code

        power = InviteCode(id="p", code=POWER_CODE, is_active=True, is_power=True)
        guest = InviteCode(id="g", code="guest", is_active=True, is_power=False)
        by_value = {POWER_CODE: power, "guest": guest}

        fake_firestore = MagicMock()
        fake_firestore.get_invite_code_by_value = MagicMock(
            side_effect=lambda c: by_value.get(c)
        )
        monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

        assert _validate_ws_invite_code(MASTER_CODE) is True
        assert _validate_ws_invite_code(POWER_CODE) is True
        assert _validate_ws_invite_code("guest") is False
        assert _validate_ws_invite_code("unknown") is False
        assert _validate_ws_invite_code(None) is False

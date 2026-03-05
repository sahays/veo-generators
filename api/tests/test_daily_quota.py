"""Tests for credit-based daily quota middleware, invite code auth, and master code bypass."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the api directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set MASTER_INVITE_CODE before importing app modules
os.environ["MASTER_INVITE_CODE"] = "master-secret"


from models import InviteCode  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) TestBrowser/1.0"
MASTER_CODE = "master-secret"
REGULAR_CODE = "regular-code"

# Endpoint URLs by credit type
TEXT_URL = "/api/v1/diagnostics/optimize-prompt"  # 1 credit
IMAGE_URL = "/api/v1/diagnostics/generate-image"  # 2 credits
VIDEO_URL = "/api/v1/diagnostics/generate-video"  # 5 credits
STITCH_URL = "/api/v1/productions/p-test/stitch"  # 0 credits
GET_URL = "/api/v1/productions"  # not credit-consuming


def _make_invite(daily_credits: int = 250) -> InviteCode:
    return InviteCode(code=REGULAR_CODE, label="test", daily_credits=daily_credits)


def _mock_firestore(daily_credits: int = 250, current_usage: int = 0):
    """Return a MagicMock that behaves like FirestoreService for quota tests."""
    mock = MagicMock()
    mock.get_invite_code_by_value.return_value = _make_invite(daily_credits)
    mock.get_daily_usage.return_value = current_usage
    mock.increment_daily_usage.return_value = current_usage + 1
    mock.get_productions.return_value = []
    mock.get_production.return_value = None
    return mock


def _mock_ai_svc():
    """Return a mock AI service with async methods returning serializable data."""
    mock = MagicMock()
    mock.analyze_brief = AsyncMock(return_value={"result": "ok"})
    mock.generate_frame = AsyncMock(return_value={"result": "ok"})
    return mock


def _mock_video_svc():
    """Return a mock video service with async methods returning serializable data."""
    mock = MagicMock()
    mock.generate_scene_video = AsyncMock(
        return_value={"operation_name": "op-test", "status": "pending"}
    )
    return mock


def _mock_storage_svc():
    """Return a mock storage service."""
    mock = MagicMock()
    mock.get_signed_url.return_value = "https://signed-url.example.com"
    return mock


@pytest.fixture(autouse=True)
def _patch_deps():
    """Patch deps so no real GCP services are needed."""
    import deps

    mock_fs = _mock_firestore()
    with (
        patch.object(deps, "firestore_svc", mock_fs),
        patch.object(deps, "ai_svc", _mock_ai_svc()),
        patch.object(deps, "video_svc", _mock_video_svc()),
        patch.object(deps, "transcoder_svc", MagicMock()),
        patch.object(deps, "storage_svc", _mock_storage_svc()),
    ):
        yield mock_fs


@pytest.fixture()
def client():
    from main import app
    from starlette.testclient import TestClient

    return TestClient(app, raise_server_exceptions=False)


# ===================================================================
# 1. Requests with no invite code are rejected
# ===================================================================


class TestNoInviteCode:
    def test_api_post_no_code_returns_403(self, client):
        resp = client.post(
            TEXT_URL,
            json={"concept": "test"},
            headers={"User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 403
        assert "Invite code required" in resp.json()["detail"]

    def test_api_get_no_code_returns_403(self, client):
        resp = client.get(GET_URL, headers={"User-Agent": BROWSER_UA})
        assert resp.status_code == 403
        assert "Invite code required" in resp.json()["detail"]

    def test_health_no_code_allowed(self, client):
        resp = client.get("/health", headers={"User-Agent": BROWSER_UA})
        assert resp.status_code == 200

    def test_validate_no_code_allowed(self, client):
        resp = client.post(
            "/api/v1/auth/validate",
            json={"code": "anything"},
            headers={"User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 200

    def test_invalid_code_returns_403(self, client, _patch_deps):
        _patch_deps.get_invite_code_by_value.return_value = None
        resp = client.post(
            TEXT_URL,
            json={"concept": "test"},
            headers={
                "X-Invite-Code": "bad-code",
                "User-Agent": BROWSER_UA,
            },
        )
        assert resp.status_code == 403
        assert "Invalid invite code" in resp.json()["detail"]


# ===================================================================
# 2. Credit costs per endpoint type
# ===================================================================


class TestCreditCosts:
    def test_text_endpoint_costs_1_credit(self, client, _patch_deps):
        _patch_deps.get_daily_usage.return_value = 0
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(250)

        resp = client.post(
            TEXT_URL,
            json={"concept": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 200
        _patch_deps.increment_daily_usage.assert_called_once()
        # Check the amount argument is 1
        call_args = _patch_deps.increment_daily_usage.call_args
        assert call_args[0][2] == 1 or call_args[1].get("amount") == 1

    def test_image_endpoint_costs_2_credits(self, client, _patch_deps):
        _patch_deps.get_daily_usage.return_value = 0
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(250)

        resp = client.post(
            IMAGE_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 200
        _patch_deps.increment_daily_usage.assert_called_once()
        call_args = _patch_deps.increment_daily_usage.call_args
        assert call_args[0][2] == 2

    def test_video_endpoint_costs_5_credits(self, client, _patch_deps):
        _patch_deps.get_daily_usage.return_value = 0
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(250)

        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 200
        _patch_deps.increment_daily_usage.assert_called_once()
        call_args = _patch_deps.increment_daily_usage.call_args
        assert call_args[0][2] == 5

    def test_stitch_costs_0_credits(self, client, _patch_deps):
        """Stitch endpoint costs 0 credits — should not increment usage."""
        _patch_deps.get_daily_usage.return_value = 999
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(250)

        resp = client.post(
            STITCH_URL,
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        # Should not be 429 since cost is 0
        assert resp.status_code != 429
        # Should not increment since cost is 0
        _patch_deps.increment_daily_usage.assert_not_called()


# ===================================================================
# 3. Credit-based quota enforcement
# ===================================================================


class TestCreditQuota:
    def test_video_blocked_when_insufficient_credits(self, client, _patch_deps):
        """With 12 credits budget and 10 used, a video (5 credits) should be blocked."""
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(
            daily_credits=12
        )
        _patch_deps.get_daily_usage.return_value = 10

        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert "credits_used" in body
        assert body["credits_used"] == 10
        assert body["daily_credits"] == 12
        assert body["credit_cost"] == 5

    def test_two_videos_then_blocked(self, client, _patch_deps):
        """With 12 credits: 2 video calls (10 credits) succeed, 3rd blocked."""
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(
            daily_credits=12
        )
        # First call: 0 used
        _patch_deps.get_daily_usage.return_value = 0
        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code != 429

        # Second call: 5 used
        _patch_deps.get_daily_usage.return_value = 5
        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code != 429

        # Third call: 10 used, 10+5=15 > 12
        _patch_deps.get_daily_usage.return_value = 10
        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 429

    def test_429_has_retry_after(self, client, _patch_deps):
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(
            daily_credits=1
        )
        _patch_deps.get_daily_usage.return_value = 1

        resp = client.post(
            TEXT_URL,
            json={"concept": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 429
        retry = int(resp.headers["Retry-After"])
        assert 0 < retry <= 86400

    def test_get_endpoints_not_credit_checked(self, client, _patch_deps):
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(1)
        _patch_deps.get_daily_usage.return_value = 999

        resp = client.get(
            GET_URL,
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code != 429
        _patch_deps.increment_daily_usage.assert_not_called()


# ===================================================================
# 4. Master code — never blocked, but usage is tracked
# ===================================================================


class TestMasterCodeBypass:
    def test_master_code_bypasses_quota(self, client, _patch_deps):
        _patch_deps.get_daily_usage.return_value = 99999

        resp = client.post(
            VIDEO_URL,
            json={"prompt": "test"},
            headers={"X-Invite-Code": MASTER_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code != 429
        # Master should still track usage
        _patch_deps.increment_daily_usage.assert_called_once()
        call_args = _patch_deps.increment_daily_usage.call_args
        assert call_args[0][2] == 5  # video costs 5 credits

    def test_master_code_on_multiple_endpoints(self, client, _patch_deps):
        rate_limited_paths = [TEXT_URL, IMAGE_URL, VIDEO_URL]
        for path in rate_limited_paths:
            resp = client.post(
                path,
                json={},
                headers={"X-Invite-Code": MASTER_CODE, "User-Agent": BROWSER_UA},
            )
            assert resp.status_code != 429, f"Master code got 429 on {path}"


# ===================================================================
# 5. Credit cost path matching
# ===================================================================


class TestPathMatching:
    def test_credit_costs_match(self):
        from main import _get_credit_cost

        assert _get_credit_cost("POST", "/api/v1/productions/p-abc123/analyze") == 1
        assert (
            _get_credit_cost("POST", "/api/v1/productions/p-abc123/scenes/s-xyz/frame")
            == 2
        )
        assert (
            _get_credit_cost("POST", "/api/v1/productions/p-abc123/scenes/s-xyz/video")
            == 5
        )
        assert _get_credit_cost("POST", "/api/v1/productions/p-abc123/stitch") == 0
        assert _get_credit_cost("POST", "/api/v1/key-moments/analyze") == 1
        assert _get_credit_cost("POST", "/api/v1/thumbnails/analyze") == 1
        assert _get_credit_cost("POST", "/api/v1/thumbnails/th-abc/collage") == 2
        assert _get_credit_cost("POST", "/api/v1/diagnostics/optimize-prompt") == 1
        assert _get_credit_cost("POST", "/api/v1/diagnostics/generate-image") == 2
        assert _get_credit_cost("POST", "/api/v1/diagnostics/generate-video") == 5

    def test_non_credit_paths_return_none(self):
        from main import _get_credit_cost

        assert _get_credit_cost("GET", "/api/v1/productions") is None
        assert _get_credit_cost("GET", "/api/v1/productions/p-abc123") is None
        assert _get_credit_cost("POST", "/api/v1/productions") is None
        assert _get_credit_cost("POST", "/api/v1/auth/validate") is None
        assert _get_credit_cost("GET", "/health") is None
        assert _get_credit_cost("POST", "/api/v1/productions/p-abc123/archive") is None

    def test_render_returns_dynamic_cost(self):
        from main import _get_credit_cost

        # render returns dynamic cost based on production scenes
        # With no firestore/production it returns 0
        cost = _get_credit_cost("POST", "/api/v1/productions/p-abc123/render")
        assert cost == 0  # no production found = 0


# ===================================================================
# 6. Credits NOT charged on failed requests
# ===================================================================


class TestCreditsOnFailure:
    def test_no_credits_charged_on_500(self, client, _patch_deps):
        """If the endpoint returns 500, credits should NOT be charged."""
        import deps

        # Make the AI service raise an error to trigger 500
        deps.ai_svc.analyze_brief = AsyncMock(side_effect=Exception("AI error"))

        _patch_deps.get_daily_usage.return_value = 0
        _patch_deps.get_invite_code_by_value.return_value = _make_invite(250)

        resp = client.post(
            TEXT_URL,
            json={"concept": "test"},
            headers={"X-Invite-Code": REGULAR_CODE, "User-Agent": BROWSER_UA},
        )
        assert resp.status_code == 500
        _patch_deps.increment_daily_usage.assert_not_called()

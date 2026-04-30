"""Tests for the Avatar feature: persona/style injection, ask endpoint, gating."""

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
def avatar():
    from models import Avatar, AvatarStyle

    return Avatar(
        id="av-test",
        name="Test",
        image_gcs_uri="gs://bucket/avatars/test.png",
        style=AvatarStyle.funny,
        persona_prompt="A cheerful test avatar.",
    )


class TestSystemInstruction:
    def test_includes_persona_and_style(self, avatar):
        from avatar_service import build_system_instruction

        sys_inst = build_system_instruction(avatar)
        assert "A cheerful test avatar." in sys_inst
        assert "funny" in sys_inst.lower()
        assert "25 words" in sys_inst
        assert avatar.name in sys_inst

    def test_works_without_persona(self):
        from avatar_service import build_system_instruction
        from models import Avatar, AvatarStyle

        bare = Avatar(
            id="av-bare",
            name="Bare",
            image_gcs_uri="gs://bucket/x.png",
            style=AvatarStyle.serious,
        )
        sys_inst = build_system_instruction(bare)
        assert "Bare" in sys_inst
        assert "serious" in sys_inst.lower()


class TestRenderPrompt:
    def test_render_prompt_includes_answer_and_style(self, avatar):
        from avatar_service import build_render_prompt

        prompt = build_render_prompt(avatar, "Hello world.")
        assert "Hello world." in prompt
        assert "funny" in prompt.lower()
        assert "lip" in prompt.lower() or "speak" in prompt.lower()


class TestAnswerQuestion:
    def test_uses_flash_lite_and_persona(self, avatar, monkeypatch):
        """Verify Gemini is called with the Flash Lite model and the persona system instruction."""
        import deps
        import avatar_service

        captured = {}

        class FakeUsageMeta:
            prompt_token_count = 50
            candidates_token_count = 20

        class FakeResponse:
            text = "I'm doing great, thanks for asking!"
            usage_metadata = FakeUsageMeta()

        def fake_generate_content(*, model, contents, config):
            captured["model"] = model
            captured["system_instruction"] = config.system_instruction
            captured["contents"] = contents
            return FakeResponse()

        fake_client = MagicMock()
        fake_client.models.generate_content = fake_generate_content
        fake_gemini = MagicMock()
        fake_gemini._get_client = lambda region=None: fake_client
        monkeypatch.setattr(deps, "gemini_svc", fake_gemini)
        monkeypatch.setattr(deps, "firestore_svc", None)

        answer, usage, model_id = avatar_service.answer_question(
            avatar=avatar,
            question="How are you?",
            history=[],
        )

        assert answer == "I'm doing great, thanks for asking!"
        assert "flash-lite" in captured["model"]
        assert "A cheerful test avatar." in captured["system_instruction"]
        assert "funny" in captured["system_instruction"].lower()
        assert usage.input_tokens == 50
        assert usage.output_tokens == 20

    def test_includes_history(self, avatar, monkeypatch):
        import deps
        import avatar_service

        captured = {}

        class FakeUsageMeta:
            prompt_token_count = 0
            candidates_token_count = 0

        class FakeResponse:
            text = "ok"
            usage_metadata = FakeUsageMeta()

        def fake_generate_content(*, model, contents, config):
            captured["contents"] = contents
            return FakeResponse()

        fake_client = MagicMock()
        fake_client.models.generate_content = fake_generate_content
        fake_gemini = MagicMock()
        fake_gemini._get_client = lambda region=None: fake_client
        monkeypatch.setattr(deps, "gemini_svc", fake_gemini)
        monkeypatch.setattr(deps, "firestore_svc", None)

        avatar_service.answer_question(
            avatar=avatar,
            question="And after that?",
            history=[
                {"role": "user", "content": "First question"},
                {"role": "model", "content": "First answer"},
            ],
        )
        # 2 history + 1 current = 3 contents
        assert len(captured["contents"]) == 3


# ----------------------------------------------------------------------------
# End-to-end ask endpoint with TestClient — covers middleware gating too.
# ----------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models import Avatar, AvatarStyle, AvatarTurn, InviteCode

    test_avatar = Avatar(
        id="av-fixture",
        name="Aanya",
        image_gcs_uri="gs://bucket/aanya.png",
        style=AvatarStyle.to_the_point,
    )

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
    fake_firestore.get_avatar = MagicMock(return_value=test_avatar)
    fake_firestore.create_avatar_turn = MagicMock()

    def fake_create(turn: AvatarTurn):
        # mimic firestore.set
        return None

    fake_firestore.create_avatar_turn = MagicMock(side_effect=fake_create)
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    # Stub Gemini answer
    import avatar_service

    def fake_answer(avatar, question, history=None, model_id=None, region=None):
        from models import UsageMetrics

        return (
            "Sure thing.",
            UsageMetrics(model_name="test"),
            "gemini-3.1-flash-lite-preview",
        )

    monkeypatch.setattr(avatar_service, "answer_question", fake_answer)

    return TestClient(app)


class TestAskEndpoint:
    def test_ask_returns_answer_and_turn(self, client):
        res = client.post(
            "/api/v1/avatars/av-fixture/ask",
            headers={"X-Invite-Code": MASTER_CODE},
            json={"question": "Hello"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["answer_text"] == "Sure thing."
        assert body["turn_id"].startswith("at-")
        assert body["status"] == "pending"

    def test_guest_blocked_from_ask(self, client):
        res = client.post(
            "/api/v1/avatars/av-fixture/ask",
            headers={"X-Invite-Code": GUEST_CODE},
            json={"question": "Hello"},
        )
        assert res.status_code == 403

    def test_ask_rejects_empty_question(self, client):
        res = client.post(
            "/api/v1/avatars/av-fixture/ask",
            headers={"X-Invite-Code": MASTER_CODE},
            json={"question": "   "},
        )
        assert res.status_code == 400


# ----------------------------------------------------------------------------
# v2 (Low Latency) — Gemini Live model + voice + version field validation,
# /ask gating, and /live-config payload shape.
# ----------------------------------------------------------------------------


class TestCreateAvatarRequest:
    def test_default_version_is_v1(self):
        from models import CreateAvatarRequest

        req = CreateAvatarRequest(
            name="x",
            image_gcs_uri="gs://b/x.png",
        )
        assert req.version == "v1"
        assert req.voice is None

    def test_v1_drops_stray_voice(self):
        from models import AvatarVoice, CreateAvatarRequest

        req = CreateAvatarRequest(
            name="x",
            image_gcs_uri="gs://b/x.png",
            version="v1",
            voice=AvatarVoice.Kore,
        )
        assert req.voice is None

    def test_v2_requires_voice(self):
        from pydantic import ValidationError

        from models import CreateAvatarRequest

        with pytest.raises(ValidationError):
            CreateAvatarRequest(
                name="x",
                image_gcs_uri="gs://b/x.png",
                version="v2",
            )

    def test_v2_rejects_unknown_voice(self):
        from pydantic import ValidationError

        from models import CreateAvatarRequest

        with pytest.raises(ValidationError):
            CreateAvatarRequest.model_validate(
                {
                    "name": "x",
                    "image_gcs_uri": "gs://b/x.png",
                    "version": "v2",
                    "voice": "NotAVoice",
                }
            )

    def test_v2_accepts_known_voice(self):
        from models import AvatarVoice, CreateAvatarRequest

        req = CreateAvatarRequest(
            name="x",
            image_gcs_uri="gs://b/x.png",
            version="v2",
            voice=AvatarVoice.Aoede,
        )
        assert req.version == "v2"
        assert req.voice == AvatarVoice.Aoede


@pytest.fixture
def v2_client(monkeypatch):
    """TestClient where the fixture avatar is v2 (voice=Kore)."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models import Avatar, AvatarStyle, AvatarVoice, InviteCode

    v2_avatar = Avatar(
        id="av-v2",
        name="Lumi",
        image_gcs_uri="gs://bucket/lumi.png",
        style=AvatarStyle.to_the_point,
        version="v2",
        voice=AvatarVoice.Kore,
    )

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
    fake_firestore.get_avatar = MagicMock(return_value=v2_avatar)
    fake_firestore.update_avatar = MagicMock()
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    fake_storage = MagicMock()
    # url_signing.sign_record_urls expects (url, changed) from resolve_cached_url.
    fake_storage.resolve_cached_url = MagicMock(
        return_value=("https://signed.example/lumi.png", True)
    )
    monkeypatch.setattr(deps, "storage_svc", fake_storage)

    return TestClient(app)


class TestV2Gating:
    def test_ask_rejects_v2(self, v2_client):
        res = v2_client.post(
            "/api/v1/avatars/av-v2/ask",
            headers={"X-Invite-Code": MASTER_CODE},
            json={"question": "Hello"},
        )
        assert res.status_code == 409
        assert "live" in res.json()["detail"].lower()

    def test_ask_audio_rejects_v2(self, v2_client):
        res = v2_client.post(
            "/api/v1/avatars/av-v2/ask-audio",
            headers={"X-Invite-Code": MASTER_CODE},
            files={"audio": ("a.webm", b"\x00\x00\x00", "audio/webm")},
        )
        assert res.status_code == 409


class TestLiveConfig:
    def test_returns_payload_for_v2(self, v2_client):
        res = v2_client.get(
            "/api/v1/avatars/av-v2/live-config",
            headers={"X-Invite-Code": MASTER_CODE},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["voice"] == "Kore"
        assert body["language"] == "en-US"
        assert "Lumi" in body["system_instruction"]
        assert body["custom_avatar_url"].startswith("https://")
        assert body["default_greeting"] is None
        # Must NOT leak server-side config
        assert "access_token" not in body
        assert "model" not in body
        assert "project_id" not in body

    def test_rejects_v1(self, client):
        res = client.get(
            "/api/v1/avatars/av-fixture/live-config",
            headers={"X-Invite-Code": MASTER_CODE},
        )
        assert res.status_code == 400

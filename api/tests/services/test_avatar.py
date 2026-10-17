"""Tests for the Avatar feature: persona/style injection, ask endpoint, gating."""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

MASTER_CODE = "test-master-code"
GUEST_CODE = "test-guest-code"

os.environ["MASTER_INVITE_CODE"] = MASTER_CODE


@pytest.fixture
def avatar() -> Any:
    from models import Avatar, AvatarStyle

    return Avatar(
        id="av-test",
        name="Test",
        image_gcs_uri="gs://bucket/avatars/test.png",
        style=AvatarStyle.funny,
        persona_prompt="A cheerful test avatar.",
    )


def _mock_gemini_answer(
    monkeypatch: Any, text: str = "ok", prompt_tokens: int = 0, out_tokens: int = 0
) -> dict[str, Any]:
    import deps

    captured: dict[str, Any] = {}
    usage_meta = SimpleNamespace(
        prompt_token_count=prompt_tokens, candidates_token_count=out_tokens
    )
    resp = SimpleNamespace(text=text, usage_metadata=usage_meta)

    def fake_generate_content(
        *, model: str, contents: Any, config: Any
    ) -> SimpleNamespace:
        captured["model"] = model
        captured["system_instruction"] = config.system_instruction
        captured["contents"] = contents
        return resp

    fake_client = MagicMock()
    fake_client.models.generate_content = fake_generate_content
    fake_gemini = MagicMock()
    fake_gemini._get_client = lambda region=None: fake_client
    monkeypatch.setattr(deps, "gemini_svc", fake_gemini)
    monkeypatch.setattr(deps, "firestore_svc", None)
    return captured


class TestSystemInstruction:
    def test_includes_persona_and_style(self, avatar: Any) -> None:
        from avatar_service import build_system_instruction

        sys_inst = build_system_instruction(avatar)
        assert "A cheerful test avatar." in sys_inst
        assert "funny" in sys_inst.lower()
        assert "25 words" in sys_inst
        assert avatar.name in sys_inst

    def test_works_without_persona(self) -> None:
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
    def test_render_prompt_includes_answer_and_style(self, avatar: Any) -> None:
        from avatar_service import build_render_prompt

        prompt = build_render_prompt(avatar, "Hello world.")
        assert "Hello world." in prompt
        assert "funny" in prompt.lower()
        assert "lip" in prompt.lower() or "speak" in prompt.lower()


class TestAnswerQuestion:
    def test_uses_flash_lite_and_persona(self, avatar: Any, monkeypatch: Any) -> None:
        """Verify Gemini is called with the Flash Lite model and the persona system instruction."""
        import avatar_service

        captured = _mock_gemini_answer(
            monkeypatch,
            text="I'm doing great, thanks for asking!",
            prompt_tokens=50,
            out_tokens=20,
        )
        answer, usage, _model_id = avatar_service.answer_question(
            avatar=avatar, question="How are you?", history=[]
        )
        assert answer == "I'm doing great, thanks for asking!"
        assert "flash-lite" in captured["model"]
        assert "A cheerful test avatar." in captured["system_instruction"]
        assert "funny" in captured["system_instruction"].lower()
        assert usage.input_tokens == 50 and usage.output_tokens == 20

    def test_includes_history(self, avatar: Any, monkeypatch: Any) -> None:
        import avatar_service

        captured = _mock_gemini_answer(monkeypatch, text="ok")
        avatar_service.answer_question(
            avatar=avatar,
            question="And after that?",
            history=[
                {"role": "user", "content": "First question"},
                {"role": "model", "content": "First answer"},
            ],
        )
        assert len(captured["contents"]) == 3


def _make_guest_invite() -> Any:
    from models import InviteCode

    return InviteCode(
        id="inv-guest",
        code=GUEST_CODE,
        label="guest",
        is_active=True,
        daily_credits=1000,
        expires_at=None,
        createdAt=datetime.now(timezone.utc),
    )


def _fake_avatar_answer(
    avatar: Any,
    question: str,
    history: Any = None,
    model_id: str | None = None,
    region: str | None = None,
) -> tuple[str, Any, str]:
    from models import UsageMetrics

    return (
        "Sure thing.",
        UsageMetrics(model_name="test"),
        "gemini-3.1-flash-lite-preview",
    )


@pytest.fixture
def client(monkeypatch: Any) -> Any:
    from fastapi.testclient import TestClient

    import avatar_service
    import deps
    from main import app
    from models import Avatar, AvatarStyle

    test_avatar = Avatar(
        id="av-fixture",
        name="Aanya",
        image_gcs_uri="gs://bucket/aanya.png",
        style=AvatarStyle.to_the_point,
    )
    guest_invite = _make_guest_invite()
    fake_firestore = MagicMock()
    fake_firestore.get_invite_code_by_value = MagicMock(
        side_effect=lambda code: guest_invite if code == GUEST_CODE else None
    )
    fake_firestore.get_avatar = MagicMock(return_value=test_avatar)
    fake_firestore.create_avatar_turn = MagicMock(return_value=None)
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)
    monkeypatch.setattr(avatar_service, "answer_question", _fake_avatar_answer)
    return TestClient(app)


class TestAskEndpoint:
    def test_ask_returns_answer_and_turn(self, client: Any) -> None:
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

    def test_guest_blocked_from_ask(self, client: Any) -> None:
        res = client.post(
            "/api/v1/avatars/av-fixture/ask",
            headers={"X-Invite-Code": GUEST_CODE},
            json={"question": "Hello"},
        )
        assert res.status_code == 403

    def test_ask_rejects_empty_question(self, client: Any) -> None:
        res = client.post(
            "/api/v1/avatars/av-fixture/ask",
            headers={"X-Invite-Code": MASTER_CODE},
            json={"question": "   "},
        )
        assert res.status_code == 400


class TestCreateAvatarRequest:
    def test_default_version_is_v1(self) -> None:
        from models import CreateAvatarRequest

        req = CreateAvatarRequest(name="x", image_gcs_uri="gs://b/x.png")
        assert req.version == "v1"
        assert req.voice is None

    def test_v1_drops_stray_voice(self) -> None:
        from models import AvatarVoice, CreateAvatarRequest

        req = CreateAvatarRequest(
            name="x",
            image_gcs_uri="gs://b/x.png",
            version="v1",
            voice=AvatarVoice.Kore,
        )
        assert req.voice is None

    def test_v2_requires_voice(self) -> None:
        from pydantic import ValidationError

        from models import CreateAvatarRequest

        with pytest.raises(ValidationError):
            CreateAvatarRequest(name="x", image_gcs_uri="gs://b/x.png", version="v2")

    def test_v2_rejects_unknown_voice(self) -> None:
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

    def test_v2_accepts_known_voice(self) -> None:
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
def v2_client(monkeypatch: Any) -> Any:
    """TestClient where the fixture avatar is v2 (voice=Kore)."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models import Avatar, AvatarStyle, AvatarVoice

    v2_avatar = Avatar(
        id="av-v2",
        name="Lumi",
        image_gcs_uri="gs://bucket/lumi.png",
        style=AvatarStyle.to_the_point,
        version="v2",
        voice=AvatarVoice.Kore,
    )
    guest_invite = _make_guest_invite()
    fake_firestore = MagicMock()
    fake_firestore.get_invite_code_by_value = MagicMock(
        side_effect=lambda code: guest_invite if code == GUEST_CODE else None
    )
    fake_firestore.get_avatar = MagicMock(return_value=v2_avatar)
    fake_firestore.update_avatar = MagicMock()
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    fake_storage = MagicMock()
    fake_storage.resolve_cached_url = MagicMock(
        return_value=("https://signed.example/lumi.png", True)
    )
    monkeypatch.setattr(deps, "storage_svc", fake_storage)
    return TestClient(app)


class TestV2Gating:
    def test_ask_rejects_v2(self, v2_client: Any) -> None:
        res = v2_client.post(
            "/api/v1/avatars/av-v2/ask",
            headers={"X-Invite-Code": MASTER_CODE},
            json={"question": "Hello"},
        )
        assert res.status_code == 409
        assert "live" in res.json()["detail"].lower()

    def test_ask_audio_rejects_v2(self, v2_client: Any) -> None:
        res = v2_client.post(
            "/api/v1/avatars/av-v2/ask-audio",
            headers={"X-Invite-Code": MASTER_CODE},
            files={"audio": ("a.webm", b"\x00\x00\x00", "audio/webm")},
        )
        assert res.status_code == 409


class TestLiveConfig:
    def test_returns_payload_for_v2(self, v2_client: Any) -> None:
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
        assert "access_token" not in body
        assert "model" not in body
        assert "project_id" not in body

    def test_rejects_v1(self, client: Any) -> None:
        res = client.get(
            "/api/v1/avatars/av-fixture/live-config",
            headers={"X-Invite-Code": MASTER_CODE},
        )
        assert res.status_code == 400

    def test_live_host_resolution(self) -> None:
        from routers.avatars_live import _live_host

        assert _live_host("us") == "aiplatform.us.rep.googleapis.com"
        assert _live_host("eu") == "aiplatform.eu.rep.googleapis.com"
        assert _live_host("us-central1") == "us-central1-aiplatform.googleapis.com"
        assert _live_host("global") == "aiplatform.googleapis.com"

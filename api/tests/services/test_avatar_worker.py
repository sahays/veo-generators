"""Tests for the AvatarProcessor worker — verifies Veo Fast is invoked correctly."""

import os
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "workers"))


@pytest.fixture
def turn_and_avatar() -> tuple[Any, Any]:
    from models import Avatar, AvatarStyle, AvatarTurn

    avatar = Avatar(
        id="av-1",
        name="Aanya",
        image_gcs_uri="gs://bucket/aanya.png",
        style=AvatarStyle.serious,
    )
    turn = AvatarTurn(
        id="at-1",
        avatar_id=avatar.id,
        question="Hi",
        answer_text="Hello there.",
        status="pending",
    )
    return turn, avatar


def _setup_fake_firestore(monkeypatch: Any, avatar: Any) -> MagicMock:
    import deps

    fake_firestore = MagicMock()
    fake_firestore.get_avatar = MagicMock(return_value=avatar)
    fake_firestore.update_avatar_turn = MagicMock()
    fake_firestore.get_default_model = MagicMock(return_value=None)
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)
    return fake_firestore


def _assert_turn_completed(fake_firestore: MagicMock, turn_id: str) -> None:
    final_call = fake_firestore.update_avatar_turn.call_args_list[-1]
    args, _ = final_call
    turn_id_arg, updates = args
    assert turn_id_arg == turn_id
    assert updates["status"] == "completed"
    assert updates["video_gcs_uri"] == "gs://bucket/avatars/output.mp4"


def test_processor_calls_omni_with_image_and_audio(
    turn_and_avatar: tuple[Any, Any], monkeypatch: Any
) -> None:
    import deps
    from avatar_processor import VEO_AVATAR_MODEL_DEFAULT, AvatarProcessor

    turn, avatar = turn_and_avatar
    fake_firestore = _setup_fake_firestore(monkeypatch, avatar)
    captured: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            id="int-123",
            status="completed",
            output_video={"type": "video", "uri": "gs://bucket/avatars/output.mp4"},
        )

    fake_client = MagicMock()
    fake_client.interactions = SimpleNamespace(create=fake_create)
    fake_video_svc = MagicMock()
    fake_video_svc._get_client = lambda region=None: fake_client
    monkeypatch.setattr(deps, "video_svc", fake_video_svc)

    AvatarProcessor().process(turn)

    kwargs = captured["kwargs"]
    assert kwargs["model"] == VEO_AVATAR_MODEL_DEFAULT and kwargs["background"] is True
    assert kwargs["generation_config"]["video_config"]["task"] == "image_to_video"
    assert any(
        b.get("type") == "text" and "Hello there." in b.get("text", "")
        for b in kwargs["input"]
    )
    assert any(
        b.get("type") == "image" and b.get("uri") == avatar.image_gcs_uri
        for b in kwargs["input"]
    )
    assert kwargs["response_format"][0]["aspect_ratio"] == "9:16"
    assert kwargs["response_format"][0]["duration"] == "8s"
    _assert_turn_completed(fake_firestore, turn.id)


def test_processor_calls_veo_fast_when_configured(
    turn_and_avatar: tuple[Any, Any], monkeypatch: Any
) -> None:
    import deps
    from avatar_processor import VEO_AVATAR_MODEL_ENV, AvatarProcessor

    monkeypatch.setenv(VEO_AVATAR_MODEL_ENV, "veo-3.1-fast-generate-001")
    turn, avatar = turn_and_avatar
    fake_firestore = _setup_fake_firestore(monkeypatch, avatar)
    captured: dict[str, Any] = {}

    def fake_generate_videos(**kwargs: Any) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        gen_vid = SimpleNamespace(
            video=SimpleNamespace(uri="gs://bucket/avatars/output.mp4")
        )
        return SimpleNamespace(
            done=True, result=SimpleNamespace(generated_videos=[gen_vid])
        )

    fake_client = MagicMock()
    fake_client.models = SimpleNamespace(generate_videos=fake_generate_videos)
    fake_video_svc = MagicMock()
    fake_video_svc._get_client = lambda region=None: fake_client
    monkeypatch.setattr(deps, "video_svc", fake_video_svc)

    AvatarProcessor().process(turn)

    kwargs = captured["kwargs"]
    assert kwargs["model"] == "veo-3.1-fast-generate-001"
    assert "Hello there." in kwargs["prompt"]
    config = kwargs["config"]
    assert (
        config.duration_seconds == 8
        and config.generate_audio is True
        and config.aspect_ratio == "9:16"
    )
    assert "image" in kwargs and kwargs["image"].gcs_uri == avatar.image_gcs_uri
    _assert_turn_completed(fake_firestore, turn.id)


def test_processor_marks_failed_when_avatar_missing(
    turn_and_avatar: tuple[Any, Any], monkeypatch: Any
) -> None:
    from avatar_processor import AvatarProcessor

    turn, _ = turn_and_avatar
    fake_firestore = _setup_fake_firestore(monkeypatch, None)

    AvatarProcessor().process(turn)

    args, _ = fake_firestore.update_avatar_turn.call_args
    turn_id_arg, updates = args
    assert turn_id_arg == turn.id
    assert updates["status"] == "failed"
    assert "Avatar" in updates["error_message"]

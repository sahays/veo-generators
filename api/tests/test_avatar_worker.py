"""Tests for the AvatarProcessor worker — verifies Veo Fast is invoked correctly."""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Both api/ and workers/ live under repo root; tests run from api/ so
# we add workers/ explicitly.
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "api"))
sys.path.insert(0, os.path.join(ROOT, "workers"))


@pytest.fixture
def turn_and_avatar():
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


def test_processor_calls_veo_fast_with_image_and_audio(turn_and_avatar, monkeypatch):
    import deps
    from avatar_processor import AvatarProcessor, VEO_AVATAR_MODEL_DEFAULT

    turn, avatar = turn_and_avatar

    fake_firestore = MagicMock()
    fake_firestore.get_avatar = MagicMock(return_value=avatar)
    fake_firestore.update_avatar_turn = MagicMock()
    fake_firestore.get_default_model = MagicMock(return_value=None)
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    captured = {}

    class FakeVideo:
        uri = "gs://bucket/avatars/output.mp4"

    class FakeGeneratedVideo:
        video = FakeVideo()

    class FakeResult:
        generated_videos = [FakeGeneratedVideo()]

    class FakeOperation:
        def __init__(self):
            self.done = True
            self.result = FakeResult()

    def fake_generate_videos(**kwargs):
        captured["kwargs"] = kwargs
        return FakeOperation()

    fake_models = MagicMock()
    fake_models.generate_videos = fake_generate_videos
    fake_client = MagicMock()
    fake_client.models = fake_models
    fake_video_svc = MagicMock()
    fake_video_svc._get_client = lambda region=None: fake_client
    monkeypatch.setattr(deps, "video_svc", fake_video_svc)

    AvatarProcessor().process(turn)

    kwargs = captured["kwargs"]
    assert kwargs["model"] == VEO_AVATAR_MODEL_DEFAULT
    assert "Hello there." in kwargs["prompt"]
    config = kwargs["config"]
    assert config.duration_seconds == 8
    assert config.generate_audio is True
    assert config.aspect_ratio == "9:16"
    # image-to-video reference must point at the avatar portrait
    assert "image" in kwargs
    assert kwargs["image"].gcs_uri == avatar.image_gcs_uri

    # Final firestore update flips the turn to completed with the URI
    final_call = fake_firestore.update_avatar_turn.call_args_list[-1]
    args, _ = final_call
    turn_id_arg, updates = args
    assert turn_id_arg == turn.id
    assert updates["status"] == "completed"
    assert updates["video_gcs_uri"] == "gs://bucket/avatars/output.mp4"


def test_processor_marks_failed_when_avatar_missing(turn_and_avatar, monkeypatch):
    import deps
    from avatar_processor import AvatarProcessor

    turn, _ = turn_and_avatar

    fake_firestore = MagicMock()
    fake_firestore.get_avatar = MagicMock(return_value=None)
    fake_firestore.update_avatar_turn = MagicMock()
    monkeypatch.setattr(deps, "firestore_svc", fake_firestore)

    AvatarProcessor().process(turn)

    args, _ = fake_firestore.update_avatar_turn.call_args
    turn_id_arg, updates = args
    assert turn_id_arg == turn.id
    assert updates["status"] == "failed"
    assert "Avatar" in updates["error_message"]

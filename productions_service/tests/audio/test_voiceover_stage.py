"""Voiceover stage wiring: S10 stitches the voiced clip; originals kept; config-gated."""

from __future__ import annotations

import pytest
from conftest import seed_valid_graph
from storygraph.adapters.transcribe import Transcript
from storygraph.assembly import assemble, evaluate_shot_readiness
from storygraph.audio.voice.sync import VoicedClip
from storygraph.config import Config
from storygraph.audio.stems import BuiltStems
from storygraph.pipeline.post_render import stems_stage, voiceover_stage
from storygraph.pipeline.post_render.dispatch import apply_audio_post
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, ProjectMeta, Role, Status


def _approved_run(repo: Repo) -> GenerationRun:
    shot = seed_valid_graph(repo)
    repo.put_project_meta(ProjectMeta(id="test_proj", name="Voice", status="running"))
    line = repo.get_dialogue("dlg_1")
    assert line is not None
    repo.put_dialogue(line.model_copy(update={"shot_id": shot.id}))
    uri = repo.blobs.put_bytes("clips/shot_1_1.mp4", b"OMNI", "video/mp4")
    run = GenerationRun(
        id="run_shot_1_1",
        created_by=Role.PIPELINE,
        status=Status.APPROVED,
        shot_id=shot.id,
        attempt=1,
        provider="gemini",
        model="omni",
        compiled_prompt="p",
        seed=1,
        package_hash="h",
        output_video_uri=uri,
        shot_content_hash=shot.content_hash,
    )
    return repo.add_generation_run(run)


def _sync_cfg() -> Config:
    cfg = Config()
    cfg.video.provider = "gemini"
    cfg.audio.mode = "voiceover_duck"
    return cfg


@pytest.fixture()
def fake_voicing(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _voice(
        clip: bytes,
        lines: list,
        voices: dict,
        cfg: object,
        deps: object,
        shot_ref: str = "",
    ) -> VoicedClip:
        calls.append(shot_ref)
        assert clip == b"OMNI" and set(voices) == {ln.speaker_id for ln in lines}
        return VoicedClip(b"VOICED", [], Transcript(), "duck")

    monkeypatch.setattr(voiceover_stage, "voice_clip", _voice)
    monkeypatch.setattr(voiceover_stage, "default_sync_deps", lambda cfg: object())
    return calls


def test_voiced_clip_recorded_once_and_preferred_by_assembly(
    tmp_repo: Repo, fake_voicing: list[str]
) -> None:
    run = _approved_run(tmp_repo)
    assert voiceover_stage.apply_voiceover(tmp_repo, _sync_cfg()) == [run.id]
    assert voiceover_stage.apply_voiceover(tmp_repo, _sync_cfg()) == []  # idempotent
    stored = tmp_repo.list_generation_runs(run.shot_id)[0]
    assert stored.output_video_uri == run.output_video_uri  # original kept
    assert tmp_repo.blobs.get_bytes(stored.voiced_video_uri or "") == b"VOICED"
    assert tmp_repo.get_entity("char_arjun").voice is not None  # type: ignore[union-attr]

    stitched: list[list[bytes]] = []
    assemble(
        tmp_repo, stitcher=lambda c: stitched.append(c) or b"M", prefer_voiced=True
    )
    assemble(
        tmp_repo, stitcher=lambda c: stitched.append(c) or b"M", prefer_voiced=False
    )
    assert stitched == [[b"VOICED"], [b"OMNI"]]


def test_voiceover_off_or_mock_provider_is_noop(
    tmp_repo: Repo, fake_voicing: list[str]
) -> None:
    _approved_run(tmp_repo)
    off = _sync_cfg()
    off.audio.mode = "omni"
    mock = _sync_cfg()
    mock.video.provider = "mock"
    assert voiceover_stage.apply_voiceover(tmp_repo, off) == []
    assert voiceover_stage.apply_voiceover(tmp_repo, mock) == []
    assert fake_voicing == []
    assert (
        evaluate_shot_readiness(tmp_repo, prefer_voiced=True)
        .ready_shots[0]
        .video_uri.endswith("shot_1_1.mp4")
    )


def test_stems_mode_records_stems_once_and_skips_voiceover(
    tmp_repo: Repo, monkeypatch: pytest.MonkeyPatch, fake_voicing: list[str]
) -> None:
    run = _approved_run(tmp_repo)
    built = BuiltStems(b"DIA", b"SFX", 8.0, [], Transcript())
    monkeypatch.setattr(stems_stage, "build_stems", lambda *a, **k: built)
    monkeypatch.setattr(stems_stage, "default_stem_deps", lambda cfg: _FakeStemDeps())
    cfg = _sync_cfg()
    cfg.audio.mode = "stems"
    assert apply_audio_post(tmp_repo, cfg) == [run.id]
    assert (
        apply_audio_post(tmp_repo, cfg) == []
    )  # stems stored; remix needs no re-render
    stored = tmp_repo.list_generation_runs(run.shot_id)[0]
    assert stored.stems is not None and stored.voiced_video_uri is None
    assert tmp_repo.blobs.get_bytes(stored.stems.sfx_uri) == b"SFX"
    assert fake_voicing == []  # voiceover_duck path never ran


class _FakeStemDeps:
    class sfx:  # noqa: N801 - minimal stand-in for StemDeps.sfx
        name = "demucs"

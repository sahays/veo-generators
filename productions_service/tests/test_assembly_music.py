"""Assembly music bed: skipped without MusicCue audio, mixed (ffmpeg mocked) when present."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest
from storygraph.assembly import assemble, build_scene_segments
from storygraph.assembly import music_ffmpeg as mix_mod
from storygraph.assembly.music import SceneSegment
from storygraph.config import AssemblyCfg
from storygraph.errors import ShotsNotApproved
from storygraph.repo import Repo
from storygraph.schema import Asset, MusicCue, Role, Status
from test_assembly_gate import _add_run, _RecordingStitcher, _seed_shots


class _RecordingMixer:
    def __init__(self) -> None:
        self.calls: list[list[SceneSegment]] = []

    def __call__(
        self, video: bytes, segments: list[SceneSegment], cfg: AssemblyCfg
    ) -> bytes:
        self.calls.append(segments)
        return b"SCORED:" + video


def _approve_all(repo: Repo) -> None:
    _seed_shots(repo)
    for shot_id in ("shot_a", "shot_b", "shot_c"):
        _add_run(repo, shot_id, 1, Status.APPROVED)


def _add_scene_music(repo: Repo) -> None:
    uri = repo.blobs.put_bytes("audio/scn_1.wav", b"RIFFmusic", "audio/wav")
    asset = repo.add_asset(
        Asset(
            id="ast_music_scn_1",
            created_by=Role.MUSIC_DIRECTOR,
            status=Status.APPROVED,
            kind="audio",
            uri=uri,
            sha256="s",
            generation_prompt="score",
            model="lyria",
        )
    )
    repo.put_music_cue(
        MusicCue(
            id="mc_scn_1",
            created_by=Role.MUSIC_DIRECTOR,
            scene_id="scn_1",
            mood="warm",
            instrumentation="strings",
            tempo_bpm=90,
            audio_asset_id=asset.id,
        )
    )


def test_no_music_assets_skips_mixer(
    tmp_repo: Repo, caplog: pytest.LogCaptureFixture
) -> None:
    _approve_all(tmp_repo)
    mixer = _RecordingMixer()
    with caplog.at_level(logging.INFO):
        uri = assemble(tmp_repo, stitcher=_RecordingStitcher(), music_mixer=mixer)
    assert mixer.calls == []
    assert tmp_repo.blobs.get_bytes(uri).startswith(b"STITCHED:")
    assert any(r.getMessage() == "no music assets; skipped" for r in caplog.records)


def test_music_assets_are_mixed_per_scene(tmp_repo: Repo) -> None:
    _approve_all(tmp_repo)
    _add_scene_music(tmp_repo)
    mixer = _RecordingMixer()
    uri = assemble(
        tmp_repo,
        stitcher=_RecordingStitcher(),
        music_mixer=mixer,
        duration_probe=lambda clip: 4.0,
    )
    assert tmp_repo.blobs.get_bytes(uri).startswith(b"SCORED:STITCHED:")
    assert mixer.calls == [[SceneSegment("scn_1", 0.0, 12.0, b"RIFFmusic")]]


def test_strict_mode_blocks_before_any_mixing(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    _add_scene_music(tmp_repo)
    _add_run(tmp_repo, "shot_a", 1, Status.APPROVED)
    mixer = _RecordingMixer()
    with pytest.raises(ShotsNotApproved):
        assemble(tmp_repo, stitcher=_RecordingStitcher(), music_mixer=mixer)
    assert mixer.calls == []


def test_segments_merge_consecutive_scene_clips() -> None:
    segs = build_scene_segments(
        ["s1", "s1", "s2", "s1"], [4.0, 5.0, 3.0, 2.0], {"s1": b"m1", "s2": None}
    )
    assert [(s.scene_id, s.start_s, s.duration_s) for s in segs] == [
        ("s1", 0.0, 9.0),
        ("s2", 9.0, 3.0),
        ("s1", 12.0, 2.0),
    ]


def test_ffmpeg_mixer_builds_ducked_crossfaded_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, list[str]] = {}

    def _fake_run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"M" * 400)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(mix_mod.shutil, "which", lambda _b: "/usr/bin/ffmpeg")
    monkeypatch.setattr(mix_mod.subprocess, "run", _fake_run)
    segs = [SceneSegment("s1", 0.0, 9.0, b"m1"), SceneSegment("s2", 9.0, 3.0, None)]
    out = mix_mod.ffmpeg_music_mixer(b"VIDEO", segs, AssemblyCfg(music_crossfade_s=4.0))
    assert out == b"M" * 400
    graph = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "acrossfade=d=1.500" in graph  # clamped to half the shortest scene
    assert "anullsrc" in graph and "sidechaincompress" in graph
    assert captured["cmd"].count("-stream_loop") == 1


def test_ffmpeg_mixer_failure_keeps_stitched_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mix_mod.shutil, "which", lambda _b: "/usr/bin/ffmpeg")
    monkeypatch.setattr(
        mix_mod.subprocess,
        "run",
        lambda cmd, **_kw: subprocess.CompletedProcess(cmd, 1, b"", b"no audio stream"),
    )
    segs = [SceneSegment("s1", 0.0, 9.0, b"m1")]
    assert mix_mod.ffmpeg_music_mixer(b"VIDEO", segs, AssemblyCfg()) == b"VIDEO"

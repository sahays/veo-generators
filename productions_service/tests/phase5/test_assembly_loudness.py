"""Assembly: EBU R128 loudnorm on the master (ffmpeg mocked) and probed clip durations."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from storygraph.assembly import assemble
from storygraph.assembly import loudness as ln
from storygraph.repo import Repo
from storygraph.schema import Status
from test_assembly_gate import _add_run, _RecordingStitcher, _seed_shots
from test_assembly_music import _add_scene_music, _RecordingMixer

_MEASURED = (
    '[Parsed_loudnorm_0 @ 0x1]\n{\n "input_i" : "-30.12", "input_tp" : "-4.50",'
    ' "input_lra" : "6.20", "input_thresh" : "-40.70", "target_offset" : "0.35"\n}\n'
)


def _fake_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, measure_rc: int = 0
) -> list[list[str]]:
    calls: list[list[str]] = []

    def _run(cmd: list[str], **_kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        if cmd[-1] == "-":  # measurement pass writes to the null muxer
            return subprocess.CompletedProcess(cmd, measure_rc, b"", _MEASURED.encode())
        Path(cmd[-1]).write_bytes(b"N" * 400)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ln.shutil, "which", lambda _b: "/usr/bin/ffmpeg")
    monkeypatch.setattr(ln.subprocess, "run", _run)
    return calls


def _af(cmd: list[str]) -> str:
    return cmd[cmd.index("-af") + 1]


def test_loudnorm_two_pass_targets_ebu_r128(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_ffmpeg(monkeypatch)
    assert ln.ffmpeg_loudnorm(b"MASTER") == b"N" * 400
    assert len(calls) == 2
    assert _af(calls[0]) == "loudnorm=I=-23:TP=-1:LRA=11:print_format=json"
    second = _af(calls[1])
    assert second.startswith("loudnorm=I=-23:TP=-1:LRA=11:")
    for part in (
        "measured_I=-30.12",
        "measured_TP=-4.50",
        "measured_LRA=6.20",
        "measured_thresh=-40.70",
        "offset=0.35",
        "linear=true",
    ):
        assert part in second
    assert calls[1][calls[1].index("-c:v") + 1] == "copy"
    assert calls[1][calls[1].index("-ar") + 1] == "48000"


def test_loudnorm_failure_keeps_master(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _fake_ffmpeg(monkeypatch, measure_rc=1)
    assert ln.ffmpeg_loudnorm(b"MASTER") == b"MASTER"
    assert len(calls) == 1  # no apply pass without valid measurements


def test_assembly_uses_probed_durations_and_normalizes_mixed_master(
    tmp_repo: Repo,
) -> None:
    _seed_shots(tmp_repo)
    for shot_id in ("shot_a", "shot_b", "shot_c"):
        _add_run(tmp_repo, shot_id, 1, Status.APPROVED)
    _add_scene_music(tmp_repo)
    planned = sum(s.duration_s for s in tmp_repo.list_shots())
    probed = {b"shot_a#1": 7.4, b"shot_b#1": 7.6, b"shot_c#1": None}
    mixer, normalized = _RecordingMixer(), []

    def _norm(video: bytes) -> bytes:
        normalized.append(video)
        return b"R128:" + video

    uri = assemble(
        tmp_repo,
        stitcher=_RecordingStitcher(),
        music_mixer=mixer,
        duration_probe=lambda clip: probed[clip],
        normalizer=_norm,
    )
    shot_c = tmp_repo.get_shot("shot_c")
    assert shot_c is not None
    total = mixer.calls[0][0].duration_s
    assert total == pytest.approx(7.4 + 7.6 + shot_c.duration_s)  # unprobed -> planned
    assert total < planned
    assert normalized and normalized[0].startswith(b"SCORED:")
    assert tmp_repo.blobs.get_bytes(uri).startswith(b"R128:SCORED:")

"""SceneAnalysisProcessor: stages, checkpoint resume, window split, filmstrip."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any, Callable, Optional
from unittest.mock import MagicMock

import pytest

import deps
import insight_jobs.scene_analysis_processor as sap
from gemini_insights import InsightResponse
from models import SceneAnalysisRecord, UsageMetrics
from timeline_windows import Window

DURATION = 1500.0  # three 500 s windows
BUCKET = "test-bucket"
Outcome = Callable[[Window], Any]


class FakeStorage:
    """In-memory bucket that also tracks the local files the job touched."""

    bucket_name = BUCKET

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.local_paths: list[str] = []
        self.downloads = 0

    def _path(self, gcs_uri: str) -> str:
        return gcs_uri.removeprefix(f"gs://{BUCKET}/")

    def upload_bytes(self, data: bytes, path: str, content_type: str = "") -> str:
        self.objects[path] = data
        return f"gs://{BUCKET}/{path}"

    def blob_exists(self, gcs_uri: str) -> bool:
        return self._path(gcs_uri) in self.objects

    def download_bytes(self, gcs_uri: str) -> bytes:
        return self.objects[self._path(gcs_uri)]

    def download_to_file(self, gcs_uri: str, local_path: str) -> None:
        self.downloads += 1
        self.local_paths.append(local_path)
        with open(local_path, "wb") as handle:
            handle.write(b"video-bytes")

    def upload_from_file(self, local_path: str, gcs_uri: str, content_type: str) -> str:
        self.local_paths.append(local_path)
        with open(local_path, "rb") as handle:
            self.objects[self._path(gcs_uri)] = handle.read()
        return gcs_uri

    def json(self, path: str) -> dict[str, Any]:
        return json.loads(self.objects[path])


class FakeAI:
    """Records every window sent to the model and how many ran at once."""

    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []
        self.active = 0
        self.max_active = 0

    async def analyze_timeline_window(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.002)
        self.active -= 1
        result = self.outcome(kwargs["window"])
        if isinstance(result, Exception):
            raise result
        return result

    def spans(self) -> list[tuple[float, float]]:
        return sorted((c["window"].start_sec, c["window"].end_sec) for c in self.calls)


def _usage() -> UsageMetrics:
    return UsageMetrics(
        input_tokens=1000, output_tokens=100, cost_usd=0.01, model_name="m"
    )


def good(window: Window) -> InsightResponse:
    """A complete answer for `window`, in absolute seconds."""
    s, e = window.start_sec, window.end_sec
    data = {
        "summary": f"From {s:.0f} to {e:.0f}.",
        "content_title": "The Film",
        "segments": [{"start_sec": s, "end_sec": e, "title": f"Scene at {s:.0f}"}],
        "cues": [
            {"start_sec": s + 1, "end_sec": s + 3, "text": "Hi", "kind": "dialogue"}
        ],
        "entities": [
            {
                "name": "Ravi",
                "kind": "character",
                "appearances": [{"start_sec": s, "end_sec": e}],
            }
        ],
        "events": [],
        "emotions": [],
        "key_moments": [{"start_sec": s + 2, "type": "hook", "label": "Start"}],
    }
    return InsightResponse(data=data, usage=_usage(), finish_reason="STOP")


def truncated(_window: Window) -> InsightResponse:
    return InsightResponse(data={}, usage=_usage(), finish_reason="MAX_TOKENS")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Mocked services and media tools around a 1500 s video in 500 s windows."""
    storage, firestore = FakeStorage(), MagicMock()
    monkeypatch.setattr(sap, "MAX_WINDOW_SEC", 600.0)
    probes = SimpleNamespace(duration=0, cuts=0, ffmpeg=[])
    monkeypatch.setattr(deps, "storage_svc", storage)
    monkeypatch.setattr(deps, "firestore_svc", firestore)

    def _duration(path: str) -> float:
        probes.duration += 1
        return DURATION

    def _cuts(path: str) -> list[float]:
        probes.cuts += 1
        return [250.0]

    def _ffmpeg(cmd: list[str], timeout: int = 0, label: str = "") -> str:
        probes.ffmpeg.append(cmd)
        with open(cmd[-1], "wb") as handle:
            handle.write(b"jpeg-bytes")
        return ""

    monkeypatch.setattr(sap, "ffprobe_duration", _duration)
    monkeypatch.setattr(sap, "detect_cuts", _cuts)
    monkeypatch.setattr(sap, "ffprobe_video", lambda p: {"width": 1920, "height": 1080})
    monkeypatch.setattr(sap, "run_ffmpeg", _ffmpeg)
    return SimpleNamespace(storage=storage, firestore=firestore, probes=probes)


def _record() -> SceneAnalysisRecord:
    return SceneAnalysisRecord(
        id="sa-1",
        source_id="up-1",
        video_gcs_uri=f"gs://{BUCKET}/uploads/film.mp4",
        video_filename="film.mp4",
        focus="the songs",
        model_id="custom-model",
        region="us-central1",
    )


def _run(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, outcome: Outcome
) -> FakeAI:
    ai = FakeAI(outcome)
    monkeypatch.setattr(deps, "ai_svc", ai)
    sap.SceneAnalysisProcessor().process(_record())
    return ai


def _updates(env: SimpleNamespace) -> list[dict[str, Any]]:
    return [c.args[1] for c in env.firestore.update_scene_analysis.call_args_list]


def _final(env: SimpleNamespace) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for update in _updates(env):
        state.update(update)
    return state


def test_completed_job_writes_timeline_summaries_and_summed_usage(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai = _run(env, monkeypatch, good)
    assert ai.spans() == [(0.0, 500.0), (500.0, 1000.0), (1000.0, 1500.0)]
    final = _final(env)
    assert (final["status"], final["progress_pct"], final["stage"]) == (
        "completed",
        100,
        "",
    )
    assert (final["duration_sec"], final["window_count"]) == (1500.0, 3)
    assert final["summary"] == "From 0 to 500. From 500 to 1000. From 1000 to 1500."
    assert final["content_title"] == "The Film"
    assert final["counts"]["segments"] == 3 and final["counts"]["entities"] == 1
    assert (
        final["timeline_gcs_uri"] == f"gs://{BUCKET}/scene_analysis/sa-1/timeline.json"
    )
    assert (final["usage"]["input_tokens"], final["usage"]["output_tokens"]) == (
        3000,
        300,
    )
    assert final["usage"]["cost_usd"] == pytest.approx(0.03)
    timeline = env.storage.json("scene_analysis/sa-1/timeline.json")
    # One character on screen through all three windows is a single appearance.
    assert timeline["entities"][0]["appearances"] == [
        {"start_sec": 0.0, "end_sec": 1500.0}
    ]
    assert [c["id"] for c in timeline["cues"]] == ["cue-1", "cue-2", "cue-3"]
    assert timeline["cuts"] == [250.0]
    checkpoint = env.storage.json("scene_analysis/sa-1/windows/0.json")
    assert checkpoint["finish_reason"] == "STOP"
    assert "finish_reason" not in checkpoint["result"]
    assert final["stage_detail"] == ""


def test_model_call_carries_the_record_source_focus_and_overrides(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = _run(env, monkeypatch, good).calls[0]
    assert call["gcs_uri"] == f"gs://{BUCKET}/uploads/film.mp4"
    assert (call["duration_sec"], call["cuts"]) == (DURATION, [250.0])
    assert (call["focus"], call["model_id"], call["region"]) == (
        "the songs",
        "custom-model",
        "us-central1",
    )


def test_progress_updates_carry_status_stage_detail_and_rising_percent(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(env, monkeypatch, good)
    updates = _updates(env)
    assert all(
        {"status", "stage", "stage_detail", "progress_pct"} <= set(u) for u in updates
    )
    percents = [u["progress_pct"] for u in updates]
    assert percents == sorted(percents) and percents[-1] == 100
    stages = [u["stage"] for u in updates if u["stage"]]
    assert list(dict.fromkeys(stages)) == ["probe", "analyze", "merge", "filmstrip"]
    analyzing = [u for u in updates if u["stage"] == "analyze"]
    assert {u["status"] for u in analyzing} == {"analyzing"}
    assert [u["stage_detail"] for u in analyzing][1:] == [
        "window 1 of 3",
        "window 2 of 3",
        "window 3 of 3",
    ]


def test_windows_run_concurrently_but_never_more_than_four_at_once(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sap, "MAX_WINDOW_SEC", 100.0)  # 1500 s -> 17 windows
    ai = _run(env, monkeypatch, good)
    assert len(ai.calls) == 17
    assert ai.max_active == sap.WINDOW_CONCURRENCY == 4


def test_retry_reuses_checkpoints_and_only_calls_the_model_for_missing_windows(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def middle_fails(window: Window) -> Any:
        return RuntimeError("503 backend error") if window.index == 1 else good(window)

    with pytest.raises(RuntimeError, match="503 backend error"):
        _run(env, monkeypatch, middle_fails)
    # The windows that succeeded alongside the failure were checkpointed.
    saved = sorted(p for p in env.storage.objects if "/windows/" in p)
    assert saved == [
        "scene_analysis/sa-1/windows/0.json",
        "scene_analysis/sa-1/windows/2.json",
    ]
    assert all(u["status"] != "completed" for u in _updates(env))

    retry = _run(env, monkeypatch, good)
    assert retry.spans() == [(500.0, 1000.0)]
    # The probe checkpoint is reused too: no second duration read or cut scan.
    assert (env.probes.duration, env.probes.cuts) == (1, 1)
    final = _final(env)
    assert final["status"] == "completed"
    # Usage covers all three windows, including the two paid for in run one.
    assert final["usage"]["input_tokens"] == 3000
    assert final["counts"]["segments"] == 3


def test_checkpoint_for_a_different_window_range_is_not_reused(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale = {"window": {"index": 1, "start_sec": 450.0, "end_sec": 900.0}, "result": {}}
    env.storage.objects["scene_analysis/sa-1/windows/1.json"] = json.dumps(
        stale
    ).encode()
    ai = _run(env, monkeypatch, good)
    assert (500.0, 1000.0) in ai.spans() and len(ai.calls) == 3
    refreshed = env.storage.json("scene_analysis/sa-1/windows/1.json")
    assert refreshed["window"]["start_sec"] == 500.0


def test_truncated_window_is_split_in_two_and_both_halves_merged(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def big_window_truncates(window: Window) -> InsightResponse:
        return truncated(window) if window.length_sec > 300 else good(window)

    ai = _run(env, monkeypatch, big_window_truncates)
    # Window 0 splits on the 250 s cut; windows 1 and 2 at their midpoints.
    assert ai.spans() == [
        (0.0, 250.0),
        (0.0, 500.0),
        (250.0, 500.0),
        (500.0, 750.0),
        (500.0, 1000.0),
        (750.0, 1000.0),
        (1000.0, 1250.0),
        (1000.0, 1500.0),
        (1250.0, 1500.0),
    ]
    final = _final(env)
    assert final["status"] == "completed" and final["window_count"] == 3
    # Nine calls were paid for, truncated ones included.
    assert final["usage"]["input_tokens"] == 9000
    timeline = env.storage.json("scene_analysis/sa-1/timeline.json")
    assert [(s["start_sec"], s["end_sec"]) for s in timeline["segments"]] == [
        (0.0, 250.0),
        (250.0, 500.0),
        (500.0, 750.0),
        (750.0, 1000.0),
        (1000.0, 1250.0),
        (1250.0, 1500.0),
    ]
    assert timeline["entities"][0]["screen_time_sec"] == 1500.0
    checkpoint = env.storage.json("scene_analysis/sa-1/windows/0.json")
    assert checkpoint["window"] == {"index": 0, "start_sec": 0.0, "end_sec": 500.0}
    assert checkpoint["usage"]["input_tokens"] == 3000
    assert checkpoint["finish_reason"] == "split after MAX_TOKENS"
    assert (
        "0s-500s was re-analysed in two halves (finish reason: MAX_TOKENS)"
        in (final["stage_detail"])
    )


def test_unparseable_output_is_split_like_a_truncated_one(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def garbled_when_long(window: Window) -> InsightResponse:
        if window.length_sec > 300:
            return InsightResponse(data={}, usage=_usage(), finish_reason="STOP")
        return good(window)

    ai = _run(env, monkeypatch, garbled_when_long)
    assert len(ai.calls) == 9 and _final(env)["status"] == "completed"


def test_splitting_stops_at_a_bounded_depth_and_fails_the_job(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sap, "MAX_WINDOW_SEC", 2000.0)  # one 1500 s window
    ai = FakeAI(truncated)
    monkeypatch.setattr(deps, "ai_svc", ai)
    with pytest.raises(RuntimeError, match="no usable analysis"):
        sap.SceneAnalysisProcessor().process(_record())
    # 1 whole + 2 halves + 4 quarters, then no deeper.
    assert len(ai.calls) == 1 + 2 + 4
    assert min(c["window"].length_sec for c in ai.calls) == 375.0
    assert "scene_analysis/sa-1/timeline.json" not in env.storage.objects


def test_blocked_answer_fails_without_spending_calls_on_splits(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(_window: Window) -> InsightResponse:
        return InsightResponse(data={}, usage=_usage(), finish_reason="SAFETY")

    ai = FakeAI(blocked)
    monkeypatch.setattr(deps, "ai_svc", ai)
    with pytest.raises(RuntimeError, match="finish reason: SAFETY"):
        sap.SceneAnalysisProcessor().process(_record())
    assert len(ai.calls) == 3  # one per planned window, no halves


def test_single_window_video_sends_the_whole_video_once(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sap, "ffprobe_duration", lambda path: 90.0)
    ai = _run(env, monkeypatch, good)
    assert ai.spans() == [(0.0, 90.0)]
    assert _final(env)["window_count"] == 1


def test_filmstrip_is_uploaded_with_its_layout(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(env, monkeypatch, good)
    final = _final(env)
    assert (
        final["filmstrip_gcs_uri"] == f"gs://{BUCKET}/scene_analysis/sa-1/filmstrip.jpg"
    )
    assert final["filmstrip"] == {
        "tile_width": 160,
        "tile_height": 90,
        "columns": 10,
        "rows": 12,
        "interval_sec": 13.0,
        "count": 116,
    }
    assert env.storage.objects["scene_analysis/sa-1/filmstrip.jpg"] == b"jpeg-bytes"
    assert "fps=1/13:round=up,scale=160:90,tile=10x12" in env.probes.ffmpeg[0]
    assert final["stage_detail"] == ""


def test_filmstrip_failure_is_tolerated_and_noted(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken(cmd: list[str], timeout: int = 0, label: str = "") -> str:
        raise RuntimeError("Filmstrip failed (exit 1): codec not found")

    monkeypatch.setattr(sap, "run_ffmpeg", _broken)
    _run(env, monkeypatch, good)
    final = _final(env)
    assert final["status"] == "completed"
    assert final["filmstrip"] is None and final["filmstrip_gcs_uri"] is None
    assert final["stage_detail"] == "Filmstrip could not be generated"
    assert final["timeline_gcs_uri"].endswith("/timeline.json")
    assert "scene_analysis/sa-1/filmstrip.jpg" not in env.storage.objects


def test_temp_files_are_removed_after_success_and_after_failure(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(env, monkeypatch, good)
    succeeded = list(env.storage.local_paths)
    assert len(succeeded) == 2 and env.storage.downloads == 1

    env.storage.objects.clear()
    env.storage.local_paths.clear()
    with pytest.raises(RuntimeError):
        _run(env, monkeypatch, lambda window: RuntimeError("model down"))
    failed = list(env.storage.local_paths)
    assert len(failed) == 1
    assert not any(os.path.exists(path) for path in succeeded + failed)


def test_unreadable_duration_fails_the_job_before_any_model_call(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sap, "ffprobe_duration", lambda path: 0.0)
    ai = FakeAI(good)
    monkeypatch.setattr(deps, "ai_svc", ai)
    with pytest.raises(RuntimeError, match="duration could not be read"):
        sap.SceneAnalysisProcessor().process(_record())
    assert ai.calls == []


def _make_clip(path: str) -> Optional[str]:
    """Synthetic clip: black for 6 s, then white for 20 s. None if ffmpeg fails."""
    cmd = ["ffmpeg", "-y"]
    for colour, seconds in (("black", 6), ("white", 20)):
        cmd += ["-f", "lavfi", "-i", f"color={colour}:s=320x180:r=10:d={seconds}"]
    cmd += ["-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-pix_fmt", "yuv420p", path]
    done = subprocess.run(cmd, capture_output=True, timeout=120)
    return path if done.returncode == 0 else None


def _gray_pixels(image_path: str) -> bytes:
    """The image as raw 8-bit luminance, row by row."""
    cmd = ["ffmpeg", "-v", "error", "-i", image_path, "-f", "rawvideo"]
    done = subprocess.run(
        [*cmd, "-pix_fmt", "gray", "-"], capture_output=True, timeout=60
    )
    return done.stdout


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_filmstrip_tile_i_shows_the_frame_at_i_times_the_interval(
    tmp_path: Any,
) -> None:
    from ffmpeg_runner import run_ffmpeg

    clip = _make_clip(str(tmp_path / "clip.mp4"))
    if clip is None:
        pytest.skip("ffmpeg could not render the synthetic clip")
    spec = {"tile_width": 160, "tile_height": 90, "columns": 2, "rows": 1}
    sprite = str(tmp_path / "strip.jpg")
    command = sap.filmstrip_command(clip, sprite, {**spec, "interval_sec": 13.0})
    run_ffmpeg(command, label="Filmstrip")
    pixels = _gray_pixels(sprite)
    assert len(pixels) == 320 * 90  # two 160x90 tiles side by side
    row = pixels[45 * 320 : 46 * 320]
    # Tile 0 is the frame at 0 s (black), not one sampled mid-interval (white
    # from 6 s on). Tile 1 is the frame at 13 s (white).
    assert row[80] < 40
    assert row[240] > 215

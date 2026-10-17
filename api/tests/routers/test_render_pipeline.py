"""Tests for parallel render concurrency, stitching, and FFmpeg fallback."""

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import deps
from models import Project, ProjectStatus, Scene, UsageMetrics
from routers import render_helpers


def _make_production(scene_count: int = 4) -> Project:
    scenes = [
        Scene(
            id=f"scene-{i}",
            visual_description=f"Scene {i} action",
            timestamp_start=f"00:{i * 4:02d}",
            timestamp_end=f"00:{(i + 1) * 4:02d}",
        )
        for i in range(scene_count)
    ]
    return Project(
        id="p-test1234",
        name="Parallel Render Test",
        base_concept="Test concept",
        video_length="16",
        orientation="16:9",
        status=ProjectStatus.GENERATING,
        scenes=scenes,
    )


class _InMemoryFirestore:
    """Thread-safe in-memory Firestore double mirroring update_scene semantics."""

    def __init__(self, production: Project) -> None:
        self._lock = threading.Lock()
        self.production = production

    def get_production(self, production_id: str) -> Project | None:
        if production_id != self.production.id:
            return None
        return Project(**self.production.dict())

    def update_production(self, production_id: str, updates: dict[str, Any]) -> None:
        data = self.production.dict()
        for k, v in updates.items():
            if "." not in k:
                data[k] = v
        self.production = Project(**data)

    def update_scene(
        self, production_id: str, scene_id: str, updates: dict[str, Any]
    ) -> None:
        with self._lock:
            prod = self.get_production(production_id)
            if not prod:
                return
            scenes_by_id = {s.id: s.dict() for s in prod.scenes}
            target = scenes_by_id.get(scene_id)
            if not target:
                return
            target.update(updates)
            self.update_production(
                production_id, {"scenes": list(scenes_by_id.values())}
            )


def _patch_zero_wait(monkeypatch: Any) -> None:
    orig_wait = render_helpers._wait_for_stitch

    async def zero_interval_wait(
        production_id: str,
        production: Any,
        job_name: str,
        interval: int = 10,
        resolution: str = "360p",
    ) -> Any:
        return await orig_wait(
            production_id, production, job_name, interval=0, resolution=resolution
        )

    monkeypatch.setattr(render_helpers, "_wait_for_stitch", zero_interval_wait)


def _make_concurrency_tracker() -> tuple[dict[str, int], Any, Any, Any]:
    counts = {"img_cur": 0, "img_max": 0, "vid_cur": 0, "vid_max": 0}

    async def fake_generate_frame(
        project_id: str, scene: Any, orientation: str, project: Any = None
    ) -> SimpleNamespace:
        counts["img_cur"] += 1
        counts["img_max"] = max(counts["img_max"], counts["img_cur"])
        await asyncio.sleep(0.03)
        counts["img_cur"] -= 1
        data = {
            "image_url": f"gs://test-bucket/frames/{scene.id}.png",
            "generated_prompt": f"frame prompt {scene.id}",
        }
        usage = UsageMetrics(
            cost_usd=0.04,
            image_input_tokens=10,
            image_output_tokens=100,
            image_model_name="gemini-nano-banana-2.1",
        )
        return SimpleNamespace(data=data, usage=usage)

    async def fake_generate_scene_video(
        project_id: str,
        scene: Any,
        blocking: bool = False,
        project: Any = None,
        resolution: str | None = None,
        render_quality: str | None = None,
    ) -> dict[str, Any]:
        counts["vid_cur"] += 1
        counts["vid_max"] = max(counts["vid_max"], counts["vid_cur"])
        await asyncio.sleep(0.03)
        counts["vid_cur"] -= 1
        return {
            "operation_name": f"op-{scene.id}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    async def fake_poll_veo(operation_name: str, timeout: int = 600) -> dict[str, str]:
        scene_id = operation_name.replace("op-", "")
        await asyncio.sleep(0.02)
        return {
            "status": "completed",
            "video_uri": f"gs://test-bucket/videos/{scene_id}.mp4",
        }

    return counts, fake_generate_frame, fake_generate_scene_video, fake_poll_veo


def _assert_parallel_render_results(
    final_prod: Project, fake_transcoder: MagicMock, prod_id: str
) -> None:
    draft_uri = "gs://test-bucket/productions/p-test1234/stitched/draft.mp4"
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.pipeline_stage == "completed"
    assert final_prod.final_video_url == draft_uri
    assert final_prod.draft_video_url == draft_uri
    for i, s in enumerate(final_prod.scenes):
        assert s.status == "completed"
        assert s.thumbnail_url == f"gs://test-bucket/frames/scene-{i}.png"
        assert s.video_url == f"gs://test-bucket/videos/scene-{i}.mp4"
        assert s.video_resolution == "360p"
    fake_transcoder.stitch_from_uris.assert_called_once_with(
        prod_id,
        [f"gs://test-bucket/videos/scene-{i}.mp4" for i in range(4)],
        orientation="16:9",
        resolution="360p",
    )


def test_parallel_render_respects_concurrency_and_stitches(monkeypatch: Any) -> None:
    """process_render runs scenes concurrently within semaphore bounds and stitches."""
    prod = _make_production(scene_count=4)
    fake_fs = _InMemoryFirestore(prod)
    monkeypatch.setattr(deps, "firestore_svc", fake_fs)
    monkeypatch.setenv("RENDER_IMAGE_CONCURRENCY", "2")
    monkeypatch.setenv("RENDER_VIDEO_CONCURRENCY", "2")

    counts, fake_frame, fake_vid, fake_poll = _make_concurrency_tracker()
    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.return_value = (
        "jobs/stitch-123",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )
    fake_transcoder.get_job_status.return_value = "SUCCEEDED"

    monkeypatch.setattr(deps, "ai_svc", SimpleNamespace(generate_frame=fake_frame))
    monkeypatch.setattr(
        deps, "video_svc", SimpleNamespace(generate_scene_video=fake_vid)
    )
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(render_helpers, "_poll_veo_operation", fake_poll)
    _patch_zero_wait(monkeypatch)

    asyncio.run(render_helpers.process_render(prod.id))
    assert counts["img_max"] == 2
    assert counts["vid_max"] == 2
    final_prod = fake_fs.get_production(prod.id)
    assert final_prod is not None
    _assert_parallel_render_results(final_prod, fake_transcoder, prod.id)


def test_stitch_falls_back_to_ffmpeg_when_transcoder_fails(monkeypatch: Any) -> None:
    """If Cloud Transcoder fails, _stitch_production falls back to FFmpeg stitching."""
    prod = _make_production(scene_count=2)
    for i, s in enumerate(prod.scenes):
        s.thumbnail_url = f"gs://test-bucket/frames/scene-{i}.png"
        s.video_url = f"gs://test-bucket/videos/scene-{i}.mp4"
        s.status = "completed"

    fake_fs = _InMemoryFirestore(prod)
    monkeypatch.setattr(deps, "firestore_svc", fake_fs)

    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.side_effect = RuntimeError("Transcoder quota")
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(deps, "storage_svc", MagicMock())

    stitched_uri = "gs://test-bucket/productions/p-test1234/stitched/final.mp4"
    monkeypatch.setattr(
        render_helpers,
        "_ffmpeg_stitch_scenes",
        lambda pid, uris, orient, res="720p": stitched_uri,
    )

    asyncio.run(render_helpers._stitch_production(prod.id, prod))

    final_prod = fake_fs.get_production(prod.id)
    assert final_prod is not None
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.final_video_url == stitched_uri

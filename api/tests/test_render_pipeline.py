import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import deps
from models import (
    Continuity,
    Project,
    ProjectStatus,
    Scene,
    SceneEvalFinding,
    StoryboardReviewIssue,
    StoryboardReviewReport,
    UsageMetrics,
    VideoEvalReport,
)
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

    def __init__(self, production: Project):
        import threading

        self._lock = threading.Lock()
        self.production = production

    def get_production(self, production_id: str):
        if production_id != self.production.id:
            return None
        return Project(**self.production.dict())

    def update_production(self, production_id: str, updates: dict):
        data = self.production.dict()
        for k, v in updates.items():
            if "." in k:
                continue
            data[k] = v
        self.production = Project(**data)

    def update_scene(self, production_id: str, scene_id: str, updates: dict):
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


def test_parallel_render_respects_concurrency_and_stitches(monkeypatch):
    """process_render runs scenes concurrently within semaphore bounds and stitches."""
    prod = _make_production(scene_count=4)
    fake_fs = _InMemoryFirestore(prod)

    monkeypatch.setattr(deps, "firestore_svc", fake_fs)
    monkeypatch.setenv("RENDER_IMAGE_CONCURRENCY", "2")
    monkeypatch.setenv("RENDER_VIDEO_CONCURRENCY", "2")

    in_flight_images = 0
    max_in_flight_images = 0
    in_flight_videos = 0
    max_in_flight_videos = 0

    async def fake_generate_frame(project_id, scene, orientation, project=None):
        nonlocal in_flight_images, max_in_flight_images
        in_flight_images += 1
        max_in_flight_images = max(max_in_flight_images, in_flight_images)
        await asyncio.sleep(0.03)
        in_flight_images -= 1
        return SimpleNamespace(
            data={
                "image_url": f"gs://test-bucket/frames/{scene.id}.png",
                "generated_prompt": f"frame prompt {scene.id}",
            },
            usage=UsageMetrics(
                cost_usd=0.04,
                image_input_tokens=10,
                image_output_tokens=100,
                image_model_name="gemini-nano-banana-2.1",
            ),
        )

    async def fake_generate_scene_video(
        project_id,
        scene,
        blocking=False,
        project=None,
        resolution=None,
        render_quality=None,
    ):
        nonlocal in_flight_videos, max_in_flight_videos
        in_flight_videos += 1
        max_in_flight_videos = max(max_in_flight_videos, in_flight_videos)
        await asyncio.sleep(0.03)
        in_flight_videos -= 1
        return {
            "operation_name": f"op-{scene.id}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    async def fake_poll_veo(operation_name: str, timeout: int = 600):
        scene_id = operation_name.replace("op-", "")
        await asyncio.sleep(0.02)
        return {
            "status": "completed",
            "video_uri": f"gs://test-bucket/videos/{scene_id}.mp4",
        }

    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.return_value = (
        "jobs/stitch-123",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )
    fake_transcoder.get_job_status.return_value = "SUCCEEDED"

    monkeypatch.setattr(
        deps, "ai_svc", SimpleNamespace(generate_frame=fake_generate_frame)
    )
    monkeypatch.setattr(
        deps,
        "video_svc",
        SimpleNamespace(generate_scene_video=fake_generate_scene_video),
    )
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(render_helpers, "_poll_veo_operation", fake_poll_veo)

    orig_wait = render_helpers._wait_for_stitch

    async def zero_interval_wait(
        production_id, production, job_name, interval=10, resolution="360p"
    ):
        return await orig_wait(
            production_id, production, job_name, interval=0, resolution=resolution
        )

    monkeypatch.setattr(render_helpers, "_wait_for_stitch", zero_interval_wait)

    asyncio.run(render_helpers.process_render(prod.id))

    # Concurrency was parallel (>1) and bounded by semaphore (<=2)
    assert max_in_flight_images == 2
    assert max_in_flight_videos == 2

    final_prod = fake_fs.get_production(prod.id)
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.pipeline_stage == "completed"
    assert (
        final_prod.final_video_url
        == "gs://test-bucket/productions/p-test1234/stitched/draft.mp4"
    )
    assert (
        final_prod.draft_video_url
        == "gs://test-bucket/productions/p-test1234/stitched/draft.mp4"
    )
    for i, s in enumerate(final_prod.scenes):
        assert s.status == "completed"
        assert s.thumbnail_url == f"gs://test-bucket/frames/scene-{i}.png"
        assert s.video_url == f"gs://test-bucket/videos/scene-{i}.mp4"
        assert s.video_resolution == "360p"

    fake_transcoder.stitch_from_uris.assert_called_once_with(
        prod.id,
        [f"gs://test-bucket/videos/scene-{i}.mp4" for i in range(4)],
        orientation="16:9",
        resolution="360p",
    )


def test_five_stage_pipeline_review_eval_and_selective_regen(monkeypatch):
    """5-stage pipeline runs review_storyboard, parallel frames/videos, stitch,
    evaluate_finished_video, selective regeneration of flagged scenes, and reports
    per-step UsageMetrics on pipeline_steps."""
    prod = _make_production(scene_count=3)
    fake_fs = _InMemoryFirestore(prod)
    monkeypatch.setattr(deps, "firestore_svc", fake_fs)

    async def fake_review_storyboard(project_id, project):
        reviewed_scenes = [
            s.copy(update={"speaker_notes": f"Speaker rule for {s.id}"})
            for s in project.scenes
        ]
        report = StoryboardReviewReport(
            overall_score=94,
            summary="Added explicit speaker attribution.",
            issues=[
                StoryboardReviewIssue(
                    scene_number=2,
                    category="speaker_attribution",
                    severity="warning",
                    problem="Ambiguous speaker in two-shot",
                    fix_applied="Added speaker_notes locking lip-sync",
                )
            ],
        )
        return SimpleNamespace(
            data={
                "review_report": report,
                "continuity": Continuity(setting_notes="Warm modern studio"),
                "scenes": reviewed_scenes,
            },
            usage=UsageMetrics(
                input_tokens=1200,
                output_tokens=600,
                model_name="gemini-3.8-flash",
                cost_usd=0.0032,
            ),
        )

    frame_calls: list[str] = []
    video_calls: list[tuple[str, str]] = []

    async def fake_generate_frame(project_id, scene, orientation, project=None):
        frame_calls.append(scene.id)
        return SimpleNamespace(
            data={
                "image_url": f"gs://test-bucket/frames/{scene.id}-v{len(frame_calls)}.png",
                "generated_prompt": f"frame prompt {scene.id}",
            },
            usage=UsageMetrics(
                cost_usd=0.04,
                image_input_tokens=100,
                image_output_tokens=500,
                image_model_name="gemini-nano-banana-2.1",
            ),
        )

    async def fake_generate_scene_video(
        project_id,
        scene,
        blocking=False,
        project=None,
        resolution=None,
        render_quality=None,
    ):
        video_calls.append((scene.id, resolution or "360p"))
        return {
            "operation_name": f"op-{scene.id}-{len(video_calls)}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    async def fake_poll_veo(operation_name: str, timeout: int = 600):
        return {
            "status": "completed",
            "video_uri": f"gs://test-bucket/videos/{operation_name}.mp4",
        }

    async def fake_evaluate_finished_video(
        project_id, project, video_gcs_uri=None, iteration=1
    ):
        eval_report = VideoEvalReport(
            overall_score=68,
            passed=False,
            iteration=iteration,
            summary="Scene 2 had a floating mug anomaly.",
            findings=[
                SceneEvalFinding(
                    scene_number=2,
                    scene_id="scene-1",
                    category="prop_physics",
                    severity="critical",
                    observed_issue="Coffee mug teleported between hands",
                    regenerate_frame=False,
                    regenerate_video=True,
                    corrected_visual_description="Scene 1 action with mug resting firmly on table",
                    corrected_speaker_notes="Only protagonist speaks; listener nods silently",
                )
            ],
        )
        return SimpleNamespace(
            data={"eval_report": eval_report},
            usage=UsageMetrics(
                input_tokens=3500,
                output_tokens=450,
                model_name="gemini-3.8-flash",
                cost_usd=0.0043,
            ),
        )

    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.return_value = (
        "jobs/stitch-draft",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )
    fake_transcoder.get_job_status.return_value = "SUCCEEDED"

    monkeypatch.setattr(
        deps,
        "ai_svc",
        SimpleNamespace(
            review_storyboard=fake_review_storyboard,
            generate_frame=fake_generate_frame,
            evaluate_finished_video=fake_evaluate_finished_video,
        ),
    )
    monkeypatch.setattr(
        deps,
        "video_svc",
        SimpleNamespace(generate_scene_video=fake_generate_scene_video),
    )
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(render_helpers, "_poll_veo_operation", fake_poll_veo)

    orig_wait = render_helpers._wait_for_stitch

    async def zero_interval_wait(
        production_id, production, job_name, interval=10, resolution="360p"
    ):
        return await orig_wait(
            production_id, production, job_name, interval=0, resolution=resolution
        )

    monkeypatch.setattr(render_helpers, "_wait_for_stitch", zero_interval_wait)

    asyncio.run(
        render_helpers.process_render(
            prod.id,
            quality="draft",
            resolution="360p",
            auto_review=True,
            auto_eval=True,
            max_eval_iterations=1,
        )
    )

    final_prod = fake_fs.get_production(prod.id)
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.pipeline_stage == "completed"
    assert final_prod.review_report is not None
    assert final_prod.review_report.overall_score == 94
    assert final_prod.eval_report is not None
    assert final_prod.eval_report.regenerated_scene_ids == ["scene-1"]

    # 3 initial frames generated; scene-1 regenerated video only (regenerate_frame=False)
    assert frame_calls == ["scene-0", "scene-1", "scene-2"]
    assert len(video_calls) == 4
    assert video_calls[-1] == ("scene-1", "360p")

    # Verify scene-1 was updated with corrective prompts and eval_status="regenerated"
    s1 = final_prod.scenes[1]
    assert s1.eval_status == "regenerated"
    assert s1.regen_count == 1
    assert "mug resting firmly" in s1.visual_description

    # Verify per-step UsageMetrics on pipeline_steps
    steps_by_id = {s.step_id: s for s in final_prod.pipeline_steps}
    assert steps_by_id["review_storyboard"].status == "completed"
    assert steps_by_id["review_storyboard"].usage.input_tokens == 1200
    assert steps_by_id["generate_frames"].status == "completed"
    assert steps_by_id["generate_frames"].usage.image_generations == 3
    assert steps_by_id["generate_videos"].status == "completed"
    assert steps_by_id["generate_videos"].usage.veo_videos == 3
    assert steps_by_id["stitch_video"].status == "completed"
    assert steps_by_id["stitch_video"].usage.transcoder_tier == "sd"
    assert steps_by_id["evaluate_video"].status == "completed"
    assert steps_by_id["evaluate_video"].usage.input_tokens == 3500
    assert steps_by_id["regenerate_scenes"].status == "completed"
    assert steps_by_id["regenerate_scenes"].usage.veo_videos == 1

    # Now test Upgrade to Final (720p): reuses existing keyframes, re-renders 360p videos at 720p
    frame_calls.clear()
    video_calls.clear()
    fake_transcoder.stitch_from_uris.return_value = (
        "jobs/stitch-final",
        "gs://test-bucket/productions/p-test1234/stitched/final.mp4",
    )

    asyncio.run(
        render_helpers.process_render(
            prod.id,
            quality="final",
            resolution="720p",
            auto_review=False,
            auto_eval=False,
        )
    )

    upgraded_prod = fake_fs.get_production(prod.id)
    assert upgraded_prod.status == ProjectStatus.COMPLETED
    assert upgraded_prod.render_quality == "final"
    assert upgraded_prod.video_resolution == "720p"
    assert (
        upgraded_prod.final_video_url
        == "gs://test-bucket/productions/p-test1234/stitched/final.mp4"
    )
    # Keyframes were reused (0 new frame calls), all 3 videos re-generated at 720p!
    assert frame_calls == []
    assert video_calls == [
        ("scene-0", "720p"),
        ("scene-1", "720p"),
        ("scene-2", "720p"),
    ]
    for s in upgraded_prod.scenes:
        assert s.video_resolution == "720p"


def test_stitch_falls_back_to_ffmpeg_when_transcoder_fails(monkeypatch):
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
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.final_video_url == stitched_uri


def test_start_and_end_frames_generated_before_videos_and_rai_retry(monkeypatch):
    """Stage 2A generates both start and end frames for all scenes and completes
    before Stage 2B starts video generation; RAI content_blocked triggers auto-sanitize retry."""
    prod = _make_production(scene_count=2)
    prod.scenes[
        1
    ].visual_description = (
        "Hanuman surrounded by roaring flames and burning palace destruction"
    )
    fake_fs = _InMemoryFirestore(prod)
    monkeypatch.setattr(deps, "firestore_svc", fake_fs)

    event_log: list[str] = []
    seen_frames_at_video_start: list[tuple[str, str | None, str | None]] = []

    async def fake_generate_frame(
        project_id,
        scene,
        orientation,
        project=None,
        frame_position="start",
        start_frame_uri=None,
    ):
        event_log.append(f"frame:{scene.id}:{frame_position}")
        if frame_position == "end":
            assert start_frame_uri == f"gs://test-bucket/frames/{scene.id}-start.png"
        return SimpleNamespace(
            data={
                "image_url": f"gs://test-bucket/frames/{scene.id}-{frame_position}.png",
                "generated_prompt": f"{frame_position} prompt {scene.id}",
                "frame_position": frame_position,
            },
            usage=UsageMetrics(
                image_generations=1,
                cost_usd=0.04,
                image_input_tokens=50,
                image_output_tokens=250,
                image_model_name="gemini-nano-banana-2.1",
            ),
        )

    video_attempts: dict[str, int] = {}

    async def fake_generate_scene_video(
        project_id,
        scene,
        blocking=False,
        project=None,
        resolution=None,
        render_quality=None,
    ):
        # Verify generate_frames step is ALREADY marked completed before any video starts
        current_prod = fake_fs.get_production(project_id)
        steps_map = {s.step_id: s.status for s in current_prod.pipeline_steps}
        assert steps_map["generate_frames"] == "completed"
        assert steps_map["generate_videos"] == "running"

        attempt = video_attempts.get(scene.id, 0) + 1
        video_attempts[scene.id] = attempt
        event_log.append(f"video:{scene.id}:attempt-{attempt}")
        seen_frames_at_video_start.append(
            (scene.id, scene.thumbnail_url, scene.end_frame_url)
        )
        return {
            "operation_name": f"op-{scene.id}-a{attempt}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    async def fake_poll_veo(operation_name: str, timeout: int = 600):
        if operation_name == "op-scene-1-a1":
            return {
                "status": "failed",
                "error": "[{'message': \"The input could not be submitted. This input contains content that violates Google's Responsible AI practices.\", 'code': 'content_blocked'}]",
            }
        return {
            "status": "completed",
            "video_uri": f"gs://test-bucket/videos/{operation_name}.mp4",
        }

    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.return_value = (
        "jobs/stitch-seq",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )
    fake_transcoder.get_job_status.return_value = "SUCCEEDED"

    monkeypatch.setattr(
        deps, "ai_svc", SimpleNamespace(generate_frame=fake_generate_frame)
    )
    monkeypatch.setattr(
        deps,
        "video_svc",
        SimpleNamespace(generate_scene_video=fake_generate_scene_video),
    )
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(render_helpers, "_poll_veo_operation", fake_poll_veo)

    orig_wait = render_helpers._wait_for_stitch

    async def zero_interval_wait(
        production_id, production, job_name, interval=10, resolution="360p"
    ):
        return await orig_wait(
            production_id, production, job_name, interval=0, resolution=resolution
        )

    monkeypatch.setattr(render_helpers, "_wait_for_stitch", zero_interval_wait)

    asyncio.run(
        render_helpers.process_render(prod.id, auto_review=False, auto_eval=False)
    )

    # All 4 frame events (start & end for scene-0 and scene-1) occurred BEFORE any video event!
    first_video_idx = next(i for i, e in enumerate(event_log) if e.startswith("video:"))
    assert first_video_idx == 4
    assert all(e.startswith("frame:") for e in event_log[:4])

    # Every video call saw both start and end frames populated
    for sid, start_uri, end_uri in seen_frames_at_video_start:
        assert start_uri == f"gs://test-bucket/frames/{sid}-start.png"
        assert end_uri == f"gs://test-bucket/frames/{sid}-end.png"

    final_prod = fake_fs.get_production(prod.id)
    assert final_prod.status == ProjectStatus.COMPLETED
    # 2 scenes x 2 frames (start + end) = 4 image generations
    steps_by_id = {s.step_id: s for s in final_prod.pipeline_steps}
    assert steps_by_id["generate_frames"].usage.image_generations == 4
    # Scene 1 sanitized its prompt after content_blocked and succeeded on attempt 2
    assert video_attempts["scene-1"] == 2
    assert "burning" not in final_prod.scenes[1].visual_description.lower()

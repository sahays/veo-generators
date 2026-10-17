"""Tests for 5-stage render pipeline, review/eval/selective regen, and RAI retries."""

import asyncio
import os
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))

import deps  # noqa: E402
from models import (  # noqa: E402
    Continuity,
    Project,
    ProjectStatus,
    SceneEvalFinding,
    StoryboardReviewIssue,
    StoryboardReviewReport,
    UsageMetrics,
    VideoEvalReport,
)
from routers import render_helpers  # noqa: E402
from test_render_pipeline import (  # noqa: E402
    _InMemoryFirestore,
    _make_production,
    _patch_zero_wait,
)


async def _fake_review_storyboard(project_id: str, project: Any) -> SimpleNamespace:
    reviewed_scenes = [
        s.copy(update={"speaker_notes": f"Speaker rule for {s.id}"})
        for s in project.scenes
    ]
    issue = StoryboardReviewIssue(
        scene_number=2,
        category="speaker_attribution",
        severity="warning",
        problem="Ambiguous speaker in two-shot",
        fix_applied="Added speaker_notes locking lip-sync",
    )
    report = StoryboardReviewReport(
        overall_score=94, summary="Added explicit speaker attribution.", issues=[issue]
    )
    usage = UsageMetrics(
        input_tokens=1200,
        output_tokens=600,
        model_name="gemini-3.8-flash",
        cost_usd=0.0032,
    )
    data = {
        "review_report": report,
        "continuity": Continuity(setting_notes="Warm modern studio"),
        "scenes": reviewed_scenes,
    }
    return SimpleNamespace(data=data, usage=usage)


async def _fake_evaluate_finished_video(
    project_id: str,
    project: Any,
    video_gcs_uri: str | None = None,
    iteration: int = 1,
) -> SimpleNamespace:
    finding = SceneEvalFinding(
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
    eval_report = VideoEvalReport(
        overall_score=68,
        passed=False,
        iteration=iteration,
        summary="Scene 2 had a floating mug anomaly.",
        findings=[finding],
    )
    usage = UsageMetrics(
        input_tokens=3500,
        output_tokens=450,
        model_name="gemini-3.8-flash",
        cost_usd=0.0043,
    )
    return SimpleNamespace(data={"eval_report": eval_report}, usage=usage)


def _make_five_stage_doubles() -> tuple[
    list[str], list[tuple[str, str]], Any, Any, Any
]:
    frame_calls: list[str] = []
    video_calls: list[tuple[str, str]] = []

    async def fake_generate_frame(
        project_id: str, scene: Any, orientation: str, project: Any = None
    ) -> SimpleNamespace:
        frame_calls.append(scene.id)
        data = {
            "image_url": f"gs://test-bucket/frames/{scene.id}-v{len(frame_calls)}.png",
            "generated_prompt": f"frame prompt {scene.id}",
        }
        usage = UsageMetrics(
            cost_usd=0.04,
            image_input_tokens=100,
            image_output_tokens=500,
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
        video_calls.append((scene.id, resolution or "360p"))
        return {
            "operation_name": f"op-{scene.id}-{len(video_calls)}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    async def fake_poll_veo(operation_name: str, timeout: int = 600) -> dict[str, str]:
        return {
            "status": "completed",
            "video_uri": f"gs://test-bucket/videos/{operation_name}.mp4",
        }

    return (
        frame_calls,
        video_calls,
        fake_generate_frame,
        fake_generate_scene_video,
        fake_poll_veo,
    )


def _assert_five_stage_draft(
    final_prod: Project, frame_calls: list[str], video_calls: list[tuple[str, str]]
) -> None:
    assert final_prod.status == ProjectStatus.COMPLETED
    assert final_prod.pipeline_stage == "completed"
    assert (
        final_prod.review_report is not None
        and final_prod.review_report.overall_score == 94
    )
    assert (
        final_prod.eval_report is not None
        and final_prod.eval_report.regenerated_scene_ids == ["scene-1"]
    )
    assert frame_calls == ["scene-0", "scene-1", "scene-2"]
    assert len(video_calls) == 4 and video_calls[-1] == ("scene-1", "360p")
    s1 = final_prod.scenes[1]
    assert s1.eval_status == "regenerated" and s1.regen_count == 1
    assert "mug resting firmly" in s1.visual_description
    steps = {s.step_id: s for s in final_prod.pipeline_steps}
    assert (
        steps["review_storyboard"].status == "completed"
        and steps["review_storyboard"].usage.input_tokens == 1200
    )
    assert (
        steps["generate_frames"].status == "completed"
        and steps["generate_frames"].usage.image_generations == 3
    )
    assert (
        steps["generate_videos"].status == "completed"
        and steps["generate_videos"].usage.veo_videos == 3
    )
    assert (
        steps["stitch_video"].status == "completed"
        and steps["stitch_video"].usage.transcoder_tier == "sd"
    )
    assert (
        steps["evaluate_video"].status == "completed"
        and steps["evaluate_video"].usage.input_tokens == 3500
    )
    assert (
        steps["regenerate_scenes"].status == "completed"
        and steps["regenerate_scenes"].usage.veo_videos == 1
    )


def _assert_upgrade_to_final(
    upgraded_prod: Project, frame_calls: list[str], video_calls: list[tuple[str, str]]
) -> None:
    assert upgraded_prod.status == ProjectStatus.COMPLETED
    assert upgraded_prod.render_quality == "final"
    assert upgraded_prod.video_resolution == "720p"
    assert (
        upgraded_prod.final_video_url
        == "gs://test-bucket/productions/p-test1234/stitched/final.mp4"
    )
    assert frame_calls == []
    assert video_calls == [
        ("scene-0", "720p"),
        ("scene-1", "720p"),
        ("scene-2", "720p"),
    ]
    for s in upgraded_prod.scenes:
        assert s.video_resolution == "720p"


def _wire_render_mocks(
    monkeypatch: Any,
    fake_fs: _InMemoryFirestore,
    ai_double: Any,
    fake_vid: Any,
    fake_poll: Any,
    stitch_job: str,
    stitch_uri: str,
) -> MagicMock:
    fake_transcoder = MagicMock()
    fake_transcoder.stitch_from_uris.return_value = (stitch_job, stitch_uri)
    fake_transcoder.get_job_status.return_value = "SUCCEEDED"
    monkeypatch.setattr(deps, "firestore_svc", fake_fs)
    monkeypatch.setattr(deps, "ai_svc", ai_double)
    monkeypatch.setattr(
        deps, "video_svc", SimpleNamespace(generate_scene_video=fake_vid)
    )
    monkeypatch.setattr(deps, "transcoder_svc", fake_transcoder)
    monkeypatch.setattr(render_helpers, "_poll_veo_operation", fake_poll)
    _patch_zero_wait(monkeypatch)
    return fake_transcoder


def test_five_stage_pipeline_review_eval_and_selective_regen(monkeypatch: Any) -> None:
    """5-stage pipeline runs review_storyboard, parallel frames/videos, stitch,
    evaluate_finished_video, selective regeneration of flagged scenes, and reports
    per-step UsageMetrics on pipeline_steps."""
    prod = _make_production(scene_count=3)
    fake_fs = _InMemoryFirestore(prod)
    frame_calls, video_calls, fake_frame, fake_vid, fake_poll = (
        _make_five_stage_doubles()
    )
    ai_double = SimpleNamespace(
        review_storyboard=_fake_review_storyboard,
        generate_frame=fake_frame,
        evaluate_finished_video=_fake_evaluate_finished_video,
    )
    fake_transcoder = _wire_render_mocks(
        monkeypatch,
        fake_fs,
        ai_double,
        fake_vid,
        fake_poll,
        "jobs/stitch-draft",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )

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
    assert final_prod is not None and final_prod.status == ProjectStatus.COMPLETED
    _assert_five_stage_draft(final_prod, frame_calls, video_calls)

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
    assert upgraded_prod is not None and upgraded_prod.video_resolution == "720p"
    _assert_upgrade_to_final(upgraded_prod, frame_calls, video_calls)


async def _fake_rai_poll_veo(operation_name: str, timeout: int = 600) -> dict[str, str]:
    if operation_name == "op-scene-1-a1":
        err = "[{'message': \"The input could not be submitted. This input contains content that violates Google's Responsible AI practices.\", 'code': 'content_blocked'}]"
        return {"status": "failed", "error": err}
    return {
        "status": "completed",
        "video_uri": f"gs://test-bucket/videos/{operation_name}.mp4",
    }


def _make_seq_and_rai_doubles(
    fake_fs: _InMemoryFirestore,
) -> tuple[
    list[str], list[tuple[str, str | None, str | None]], dict[str, int], Any, Any
]:
    event_log: list[str] = []
    seen_frames: list[tuple[str, str | None, str | None]] = []
    video_attempts: dict[str, int] = {}

    async def fake_generate_frame(
        project_id: str,
        scene: Any,
        orientation: str,
        project: Any = None,
        frame_position: str = "start",
        start_frame_uri: str | None = None,
    ) -> SimpleNamespace:
        event_log.append(f"frame:{scene.id}:{frame_position}")
        if frame_position == "end":
            assert start_frame_uri == f"gs://test-bucket/frames/{scene.id}-start.png"
        data = {
            "image_url": f"gs://test-bucket/frames/{scene.id}-{frame_position}.png",
            "generated_prompt": f"{frame_position} prompt {scene.id}",
            "frame_position": frame_position,
        }
        usage = UsageMetrics(
            image_generations=1,
            cost_usd=0.04,
            image_input_tokens=50,
            image_output_tokens=250,
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
        current_prod = fake_fs.get_production(project_id)
        assert current_prod is not None
        steps_map = {s.step_id: s.status for s in current_prod.pipeline_steps}
        assert (
            steps_map["generate_frames"] == "completed"
            and steps_map["generate_videos"] == "running"
        )
        attempt = video_attempts.get(scene.id, 0) + 1
        video_attempts[scene.id] = attempt
        event_log.append(f"video:{scene.id}:attempt-{attempt}")
        seen_frames.append((scene.id, scene.thumbnail_url, scene.end_frame_url))
        return {
            "operation_name": f"op-{scene.id}-a{attempt}",
            "generated_prompt": f"video prompt {scene.id}",
            "model_id": "gemini-omni-1.1-flash-preview",
            "resolution": resolution or "360p",
        }

    return (
        event_log,
        seen_frames,
        video_attempts,
        fake_generate_frame,
        fake_generate_scene_video,
    )


def test_start_and_end_frames_generated_before_videos_and_rai_retry(
    monkeypatch: Any,
) -> None:
    """Stage 2A generates both start and end frames for all scenes and completes
    before Stage 2B starts video generation; RAI content_blocked triggers auto-sanitize retry."""
    prod = _make_production(scene_count=2)
    prod.scenes[
        1
    ].visual_description = (
        "Hanuman surrounded by roaring flames and burning palace destruction"
    )
    fake_fs = _InMemoryFirestore(prod)
    event_log, seen_frames, video_attempts, fake_frame, fake_vid = (
        _make_seq_and_rai_doubles(fake_fs)
    )
    _wire_render_mocks(
        monkeypatch,
        fake_fs,
        SimpleNamespace(generate_frame=fake_frame),
        fake_vid,
        _fake_rai_poll_veo,
        "jobs/stitch-seq",
        "gs://test-bucket/productions/p-test1234/stitched/draft.mp4",
    )

    asyncio.run(
        render_helpers.process_render(prod.id, auto_review=False, auto_eval=False)
    )
    first_video_idx = next(i for i, e in enumerate(event_log) if e.startswith("video:"))
    assert first_video_idx == 4 and all(e.startswith("frame:") for e in event_log[:4])
    for sid, start_uri, end_uri in seen_frames:
        assert start_uri == f"gs://test-bucket/frames/{sid}-start.png"
        assert end_uri == f"gs://test-bucket/frames/{sid}-end.png"

    final_prod = fake_fs.get_production(prod.id)
    assert final_prod is not None and final_prod.status == ProjectStatus.COMPLETED
    steps_by_id = {s.step_id: s for s in final_prod.pipeline_steps}
    assert steps_by_id["generate_frames"].usage.image_generations == 4
    assert video_attempts["scene-1"] == 2
    assert "burning" not in final_prod.scenes[1].visual_description.lower()

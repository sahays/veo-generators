"""Render state machine facade — 5-stage agent-supervised pipeline.

Re-exports all pipeline stages, state helpers, and stitch utilities from
`render_pipeline.*` so callers and tests (`routers.render_helpers`) have a
single stable interface.
"""

from __future__ import annotations

from render_pipeline.eval_regen import (
    run_selective_regenerate_step,
    run_standalone_regenerate_flagged,
    run_storyboard_review_step,
    run_video_eval_step,
)
from render_pipeline.frames import (
    _aggregate_frame_usage,
    _call_generate_frame,
    _generate_scene_frame,
    _merge_frame_usage,
    _record_frame_result,
    _run_frame_phase_for_scene,
)
from render_pipeline.orchestrator import process_render
from render_pipeline.state import (
    DEFAULT_IMAGE_CONCURRENCY,
    DEFAULT_VIDEO_CONCURRENCY,
    _RAI_NARRATION_REPLACEMENTS,
    _RAI_REPLACEMENTS,
    _ensure_steps_list,
    _fail_production,
    _fail_scene,
    _image_concurrency,
    _is_rai_blocked_error,
    _sanitize_scene_for_rai,
    _sanitize_text_for_rai,
    _scene_duration_seconds,
    _update_pipeline_step,
    _video_concurrency,
    build_initial_pipeline_steps,
)
from render_pipeline.stitch import (
    _collect_scene_uris,
    _compute_stitch_usage,
    _ffmpeg_stitch_scenes,
    _stitch_production,
    _wait_for_stitch,
)
from render_pipeline.videos import (
    _aggregate_video_usage,
    _attempt_scene_video,
    _complete_scene_video,
    _generate_scene_video,
    _persist_video_result,
    _poll_scene_video,
    _poll_veo_operation,
    _process_one_scene,
    _run_scene_video_stage,
    _run_video_phase_for_scene,
    _scene_has_valid_video,
)

__all__ = [
    "DEFAULT_IMAGE_CONCURRENCY",
    "DEFAULT_VIDEO_CONCURRENCY",
    "_RAI_NARRATION_REPLACEMENTS",
    "_RAI_REPLACEMENTS",
    "_aggregate_frame_usage",
    "_aggregate_video_usage",
    "_attempt_scene_video",
    "_call_generate_frame",
    "_collect_scene_uris",
    "_complete_scene_video",
    "_compute_stitch_usage",
    "_ensure_steps_list",
    "_fail_production",
    "_fail_scene",
    "_ffmpeg_stitch_scenes",
    "_generate_scene_frame",
    "_generate_scene_video",
    "_image_concurrency",
    "_is_rai_blocked_error",
    "_merge_frame_usage",
    "_persist_video_result",
    "_poll_scene_video",
    "_poll_veo_operation",
    "_process_one_scene",
    "_record_frame_result",
    "_run_frame_phase_for_scene",
    "_run_scene_video_stage",
    "_run_video_phase_for_scene",
    "_sanitize_scene_for_rai",
    "_sanitize_text_for_rai",
    "_scene_duration_seconds",
    "_scene_has_valid_video",
    "_stitch_production",
    "_update_pipeline_step",
    "_video_concurrency",
    "_wait_for_stitch",
    "build_initial_pipeline_steps",
    "process_render",
    "run_selective_regenerate_step",
    "run_standalone_regenerate_flagged",
    "run_storyboard_review_step",
    "run_video_eval_step",
]

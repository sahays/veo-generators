"""Reframe AI and perception sub-steps: diarization, detection scan, semantics, and Pass-2 decisions."""

import logging
import os
from typing import Any, Awaitable, Callable, Optional

import deps
from cost_tracking import accumulate_diarization_cost
from models import SpeakerSegment

from _reframe_helpers import format_chirp_context, format_track_summary

logger = logging.getLogger(__name__)


def _bill_text_usage(
    record_id: str, usage: Any, accumulate_text_cost_fn: Callable[..., None]
) -> None:
    """Accumulate text token cost when usage has a non-zero cost_usd."""
    if usage and usage.cost_usd:
        accumulate_text_cost_fn(
            "reframe",
            record_id,
            cost_usd=usage.cost_usd,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            model_name=usage.model_name,
        )


def scan_and_track_video(
    record_id: str,
    det_src: str,
    cuts: list,
    sample_fps: float,
    active_area: Any = None,
) -> tuple[list, list, list, str, list]:
    """Run MediaPipe face/person detection, face tracking, and text band scanning."""
    from mediapipe_detection import scan_video_detections, track_faces
    from text_detect import scan_video_text

    logger.info(
        f"[reframe:{record_id}] MediaPipe scanning (faces+persons) @ {sample_fps}fps...",
        extra={
            "who": "reframe",
            "where": "scan_and_track_video",
            "what": f"fps={sample_fps}",
            "why": "subject_detection",
            "how": "scan_video_detections",
        },
    )
    det_frames = scan_video_detections(
        det_src, sample_fps=sample_fps, active_area=active_area
    )
    tracked_frames = track_faces(
        [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det_frames],
        cuts=cuts,
    )
    person_frames = [
        {"time_sec": f["time_sec"], "persons": f["persons"]} for f in det_frames
    ]
    track_summary = format_track_summary(tracked_frames)
    deps.firestore_svc.update_reframe_record(
        record_id, {"track_summary": track_summary}
    )
    text_frames = scan_video_text(det_src, sample_fps=2.0, active_area=active_area)
    return det_frames, tracked_frames, person_frames, track_summary, text_frames


def _transcribe_speaker_segments(
    record_id: str, src_path: str, probe: dict, tmp: Any
) -> list:
    """Extract WAV audio, upload to GCS, and run Chirp 3 speaker diarization."""
    from diarization_service import extract_audio

    audio_path = tmp.create(suffix=".wav")
    extract_audio(src_path, audio_path)
    bucket = os.getenv("GCS_BUCKET")
    audio_uri = f"gs://{bucket}/reframes/{record_id}/audio.wav"
    deps.storage_svc.upload_from_file(audio_path, audio_uri)
    result = deps.diarization_svc.transcribe_with_diarization(
        audio_gcs_uri=audio_uri,
        storage_svc=deps.storage_svc,
        record_id=record_id,
        audio_duration=probe["duration"],
    )
    speaker_segments = result.get("speaker_segments", [])
    deps.firestore_svc.update_reframe_record(
        record_id,
        {"speaker_segments": [SpeakerSegment(**s).dict() for s in speaker_segments]},
    )
    return speaker_segments


def run_diarization(
    record_id: str,
    src_path: str,
    probe: dict,
    tmp: Any,
    has_audio: bool,
    update_status_fn: Callable[[str, str, int], None],
) -> tuple[str, list]:
    """Run Chirp 3 speaker diarization whenever the source has audio."""
    svc_state = "yes" if deps.diarization_svc else "NO"
    logger.info(
        f"[reframe:{record_id}] Diarization: audio={has_audio}, svc={svc_state}",
        extra={
            "who": "reframe",
            "where": "run_diarization",
            "what": f"audio={has_audio},svc={svc_state}",
            "why": "check_audio",
            "how": "diarization_gate",
        },
    )
    if not (has_audio and deps.diarization_svc):
        return "", []

    update_status_fn(record_id, "analyzing", 10)
    logger.info(
        f"[reframe:{record_id}] Running Chirp 3 diarization...",
        extra={
            "who": "reframe",
            "where": "run_diarization",
            "what": "start_chirp3",
            "why": "speaker_turns",
            "how": "transcribe_with_diarization",
        },
    )
    try:
        speaker_segments = _transcribe_speaker_segments(record_id, src_path, probe, tmp)
        logger.info(
            f"[reframe:{record_id}] Chirp 3: {len(speaker_segments)} segments",
            extra={
                "who": "reframe",
                "where": "run_diarization",
                "what": f"segments={len(speaker_segments)}",
                "why": "diarization_done",
                "how": "format_chirp_context",
            },
        )
        accumulate_diarization_cost("reframe", record_id, probe["duration"] / 60.0)
        return format_chirp_context(speaker_segments), speaker_segments
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] Diarization skipped ({e})",
            extra={
                "who": "reframe",
                "where": "run_diarization",
                "what": "diarization_skipped",
                "why": str(e),
                "how": "fallback_empty",
            },
        )
        return "", []


def analyze_scenes(
    record: Any,
    record_id: str,
    chirp_context: str,
    track_summary: str,
    cuts: Optional[list],
    run_async: Callable[[Awaitable[Any]], Any],
    update_status_fn: Callable[[str, str, int], None],
    accumulate_text_cost_fn: Callable[..., None],
) -> list:
    """Run Gemini scene analysis, informed by cuts and MediaPipe tracks."""
    update_status_fn(record_id, "analyzing", 20)
    if getattr(record, "deterministic_only", False):
        logger.info(
            f"[reframe:{record_id}] deterministic-only: skipping Gemini scene analysis",
            extra={
                "who": "reframe",
                "where": "analyze_scenes",
                "what": "skip_gemini",
                "why": "deterministic_only",
                "how": "return_empty",
            },
        )
        return []
    logger.info(
        f"[reframe:{record_id}] Gemini scene analysis",
        extra={
            "who": "reframe",
            "where": "analyze_scenes",
            "what": "start_scene_analysis",
            "why": "scene_context",
            "how": "analyze_video_scenes",
        },
    )
    context = "\n\n".join(filter(None, [chirp_context, track_summary]))
    result = run_async(
        deps.ai_svc.analyze_video_scenes(
            gcs_uri=record.source_gcs_uri,
            mime_type="video/mp4",
            chirp_context=context,
            cuts=cuts,
            model_id=getattr(record, "model_id", None),
            region=getattr(record, "region", None),
        )
    )
    scenes = result.data.get("scenes", [])
    updates = {
        "prompt_variables": result.data.get("prompt_variables", {}),
        "prompt_text_used": result.data.get("prompt_text_used", ""),
        "gemini_scenes": scenes,
    }
    deps.firestore_svc.update_reframe_record(record_id, updates)
    usage = result.usage
    accumulate_text_cost_fn(
        "reframe",
        record_id,
        cost_usd=usage.cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        model_name=usage.model_name,
    )
    logger.info(
        f"[reframe:{record_id}] {len(scenes)} scenes from Gemini",
        extra={
            "who": "reframe",
            "where": "analyze_scenes",
            "what": f"scenes={len(scenes)}",
            "why": "gemini_done",
            "how": "update_reframe_record",
        },
    )
    return scenes


def collect_semantics(
    record_id: str,
    future: Any,
    cuts: list,
    text_frames: list,
    duration: float,
    accumulate_text_cost_fn: Callable[..., None],
) -> tuple[list, str]:
    """Join the semantic-pass thread and validate shots. Best-effort."""
    from reframe_semantic import reconcile_semantics, validate
    from text_detect import persistent_text_regions

    try:
        result = future.result(timeout=180)
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] semantic pass failed ({e}) — falling back to legacy escalations",
            extra={
                "who": "reframe",
                "where": "collect_semantics",
                "what": "semantic_failed",
                "why": str(e),
                "how": "fallback_legacy",
            },
        )
        return [], "fallback_legacy"
    _bill_text_usage(record_id, result.usage, accumulate_text_cost_fn)
    shots = validate(result.data, cuts, duration)
    if shots is None:
        logger.warning(
            f"[reframe:{record_id}] semantic payload unusable — falling back to legacy escalations",
            extra={
                "who": "reframe",
                "where": "collect_semantics",
                "what": "semantic_invalid",
                "why": "validation_failed",
                "how": "fallback_legacy",
            },
        )
        return [], "fallback_legacy"
    try:
        deps.firestore_svc.update_reframe_record(record_id, {"semantic_shots": shots})
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] semantic_shots store skipped ({e})",
            extra={
                "who": "reframe",
                "where": "collect_semantics",
                "what": "store_skipped",
                "why": str(e),
                "how": "ignore_error",
            },
        )
    scenes = reconcile_semantics(shots, persistent_text_regions(text_frames))
    covered = sum(s["end_sec"] - s["start_sec"] for s in shots)
    status = "ok" if covered >= 0.95 * max(duration, 0.001) else "partial"
    logger.info(
        f"[reframe:{record_id}] semantic pass: {len(scenes)} shots, {covered:.1f}/{duration:.1f}s covered ({status})",
        extra={
            "who": "reframe",
            "where": "collect_semantics",
            "what": f"shots={len(scenes)},status={status}",
            "why": "semantic_done",
            "how": "reconcile_semantics",
        },
    )
    return scenes, status


def apply_gemini_decisions(
    record: Any,
    record_id: str,
    segments: list[dict],
    src_path: str,
    src_w: int,
    src_h: int,
    rungs: Any,
    run_async: Callable[[Awaitable[Any]], Any],
    accumulate_text_cost_fn: Callable[..., None],
    tracked_frames: Optional[list] = None,
    person_frames: Optional[list] = None,
    active_area: Any = None,
) -> None:
    """Pass 2: resolve the planner's escalated decision points (gemini-3.5-flash)."""
    from reframe_decide import apply_verdicts, harmonize_letterbox
    from reframe_escalation import plan_batches, summarize
    from reframe_plan import collect_escalation_points

    points = collect_escalation_points(segments)
    if not points:
        return
    batch = plan_batches(points)
    logger.info(
        f"[reframe:{record_id}] {summarize(batch)}",
        extra={
            "who": "reframe",
            "where": "apply_gemini_decisions",
            "what": summarize(batch),
            "why": "escalations_planned",
            "how": "plan_batches",
        },
    )
    if not batch["batches"]:
        return
    try:
        canvas = getattr(record, "output_aspect_ratio", "9:16") or "9:16"
        coro = deps.ai_svc.decide_escalations(
            batch["batches"],
            src_path,
            region=getattr(record, "region", None),
            canvas=canvas,
            active_area=active_area,
        )
        result = run_async(coro)
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] gemini decisions skipped ({e})",
            extra={
                "who": "reframe",
                "where": "apply_gemini_decisions",
                "what": "decisions_skipped",
                "why": str(e),
                "how": "keep_fallbacks",
            },
        )
        return
    verdicts = result.data.get("verdicts", [])
    changed = apply_verdicts(
        segments, verdicts, src_w, src_h, rungs, tracked_frames, person_frames
    )
    widened = harmonize_letterbox(segments, src_w, src_h, rungs)
    logger.info(
        f"[reframe:{record_id}] gemini verdicts: {len(verdicts)} returned, {changed} segment(s) re-framed, {widened} widened across shots",
        extra={
            "who": "reframe",
            "where": "apply_gemini_decisions",
            "what": f"verdicts={len(verdicts)},changed={changed}",
            "why": "verdicts_applied",
            "how": "apply_verdicts",
        },
    )
    _bill_text_usage(record_id, result.usage, accumulate_text_cost_fn)

"""Diagnostic, detection scan, and segment planning pipeline stages for ReframeProcessor."""

from concurrent.futures import ThreadPoolExecutor
import logging
import os
from typing import Any, Optional

import deps
from _reframe_ai_pipeline import scan_and_track_video
from _reframe_helpers import ensure_cv2_readable
from base_processor import TempFileManager

logger = logging.getLogger(__name__)


def _resolve_canvas_and_rungs(record: Any) -> tuple[str, int, int, Any]:
    """Return (aspect_ratio, out_w, out_h, rungs) for a reframe record."""
    from reframe_filters import OUTPUT_CANVAS
    from reframe_plan import RUNGS_BY_CANVAS

    ar = getattr(record, "output_aspect_ratio", "9:16") or "9:16"
    out_w, out_h = OUTPUT_CANVAS.get(ar, OUTPUT_CANVAS["9:16"])
    rungs = RUNGS_BY_CANVAS.get(ar, RUNGS_BY_CANVAS["9:16"])
    return ar, out_w, out_h, rungs


def _mark_outlier_full_frame_shots(
    segments: list[dict], active_area: Any, cuts: list, dur: float
) -> None:
    """Flag segments inside outlier full-bleed shot ranges as untrimmed."""
    from reframe_active_area import outlier_shot_ranges

    for lo, hi in outlier_shot_ranges(active_area, cuts, dur):
        for seg in segments:
            if seg["start"] < hi and seg["end"] > lo:
                seg["src_full_frame"] = True


def launch_semantic_pass(
    proc: Any, record: Any, cuts: list, chirp_context: str, dur: float
) -> tuple[Any, Any]:
    """Start async whole-video semantic pass in background if enabled."""
    from reframe_semantic import semantic_pass_enabled

    if not semantic_pass_enabled(record):
        return None, None
    executor = ThreadPoolExecutor(max_workers=1)
    coro = deps.ai_svc.analyze_video_semantics(
        record.source_gcs_uri,
        cuts,
        chirp_context,
        dur,
        region=getattr(record, "region", None),
    )
    return executor.submit(proc._run_async, coro), executor


def run_diagnostic_pipeline(
    proc: Any,
    record: Any,
    record_id: str,
    src_path: str,
    out_path: str,
    probe: dict,
    tmp: TempFileManager,
) -> None:
    """Diagnostic mode: run detection, render detector overlays (no crop)."""
    from reframe_diagnostic import render_diagnostic
    from reframe_plan import attach_keypoints, reconcile
    from scene_detect import detect_cuts

    has_audio = probe.get("has_audio", True)
    ar, out_w, out_h, rungs = _resolve_canvas_and_rungs(record)
    chirp_ctx, spk_segs = proc._run_diarization(
        record, record_id, src_path, probe, tmp, has_audio
    )
    proc.update_status(record_id, "processing", 30)
    det_src = ensure_cv2_readable(src_path, tmp, record_id)
    cuts = detect_cuts(det_src)
    det_frames, tracked_frames, person_frames, track_summary, text_frames = (
        scan_and_track_video(record_id, det_src, cuts, sample_fps=4.0)
    )
    proc._dump_detection_fixture(
        record_id, probe, ar, cuts, det_frames, text_frames, spk_segs, 4.0
    )
    scenes = proc._analyze_scenes(
        record, record_id, chirp_ctx, track_summary, cuts=cuts
    )
    segments = reconcile(
        scenes,
        tracked_frames,
        cuts,
        probe["width"],
        probe["height"],
        probe["duration"],
        person_frames=person_frames,
        rungs=rungs,
        text_frames=text_frames,
    )
    attach_keypoints(segments, probe["fps"], probe["width"], probe["height"])
    proc._store_segment_plan(record_id, segments)
    proc.update_status(record_id, "processing", 60)
    logger.info(
        f"[reframe:{record_id}] Rendering diagnostic overlay ({ar})...",
        extra={
            "who": "reframe",
            "where": "_run_diagnostic",
            "what": f"ar={ar}",
            "why": "diagnostic_mode",
            "how": "render_diagnostic",
        },
    )
    render_diagnostic(
        src_path=det_src,
        out_path=out_path,
        tracked_frames=tracked_frames,
        scenes=scenes,
        src_w=probe["width"],
        src_h=probe["height"],
        has_audio=has_audio,
        person_frames=person_frames,
        segments=segments,
        out_w=out_w,
        out_h=out_h,
    )


def detect_and_scan_video(
    proc: Any,
    record: Any,
    record_id: str,
    src_path: str,
    probe: dict,
    ar: str,
    tmp: TempFileManager,
) -> dict[str, Any]:
    """Run diarization, cut detection, active-area detection, MediaPipe scan, and semantic pass."""
    from reframe_active_area import crop_prefilter, detect_active_area, rect_px
    from scene_detect import detect_cuts

    dur = probe["duration"]
    chirp_ctx, spk_segs = proc._run_diarization(
        record, record_id, src_path, probe, tmp, probe.get("has_audio", True)
    )
    proc.update_status(record_id, "analyzing", 15)
    det_src = ensure_cv2_readable(src_path, tmp, record_id)
    cuts = detect_cuts(det_src)
    logger.info(
        f"[reframe:{record_id}] {len(cuts)} cuts detected",
        extra={
            "who": "reframe",
            "where": "_detect_and_scan",
            "what": f"cuts={len(cuts)}",
            "why": "scene_boundaries",
            "how": "detect_cuts",
        },
    )
    active_area = detect_active_area(det_src)
    ax, ay, w, h = rect_px(active_area, probe["width"], probe["height"])
    src_crop = crop_prefilter((ax, ay, w, h), probe["width"], probe["height"])
    if active_area:
        logger.info(
            f"[reframe:{record_id}] baked bars detected — active picture {w}x{h}+{ax}+{ay} of {probe['width']}x{probe['height']}",
            extra={
                "who": "reframe",
                "where": "_detect_and_scan",
                "what": f"{w}x{h}+{ax}+{ay}",
                "why": "baked_bars",
                "how": "detect_active_area",
            },
        )
    sem_future, sem_exec = proc._launch_semantic_pass(record, cuts, chirp_ctx, dur)
    det_fps = float(os.getenv("REFRAME_DETECT_FPS", "4.0"))
    det_frames, tracked, persons, _, text_frames = scan_and_track_video(
        record_id, det_src, cuts, sample_fps=det_fps, active_area=active_area
    )
    proc._dump_detection_fixture(
        record_id,
        probe,
        ar,
        cuts,
        det_frames,
        text_frames,
        spk_segs,
        det_fps,
        active_area=active_area,
    )
    scenes, sem_status = (
        ([], "off")
        if sem_future is None
        else proc._collect_semantics(record_id, sem_future, cuts, text_frames, dur)
    )
    if sem_exec is not None:
        sem_exec.shutdown(wait=False)
    return {
        "det_src": det_src,
        "cuts": cuts,
        "active_area": active_area,
        "w": w,
        "h": h,
        "src_crop": src_crop,
        "det_fps": det_fps,
        "tracked_frames": tracked,
        "person_frames": persons,
        "text_frames": text_frames,
        "speaker_segments": spk_segs,
        "scenes": scenes,
        "semantic_status": sem_status,
    }


def plan_and_evaluate_segments(
    proc: Any,
    record: Any,
    record_id: str,
    scan: dict[str, Any],
    probe: dict,
    out_h: int,
    rungs: Any,
) -> tuple[list[dict], Optional[dict]]:
    """Reconcile segment plan, apply Pass-2 Gemini verdicts, and store evaluation report."""
    from mediapipe_detection import detection_backend
    from reframe_active_area import summarize as summarize_active_area
    from reframe_plan import attach_keypoints, reconcile

    w, h, dur, fps = scan["w"], scan["h"], probe["duration"], probe["fps"]
    active_area = scan["active_area"]
    proc.update_status(record_id, "processing", 40)
    segments = reconcile(
        scan["scenes"],
        scan["tracked_frames"],
        scan["cuts"],
        w,
        h,
        dur,
        person_frames=scan["person_frames"],
        rungs=rungs,
        text_frames=scan["text_frames"],
        speaker_segments=scan["speaker_segments"],
    )
    _mark_outlier_full_frame_shots(segments, active_area, scan["cuts"], dur)
    proc._apply_gemini_decisions(
        record,
        record_id,
        segments,
        scan["det_src"],
        w,
        h,
        rungs,
        scan["tracked_frames"],
        scan["person_frames"],
        active_area=active_area,
    )
    attach_keypoints(segments, fps, w, h)
    active_summary = summarize_active_area(active_area)
    proc._store_segment_plan(
        record_id,
        segments,
        semantic_status=scan["semantic_status"],
        active_area=active_summary,
    )
    logger.info(
        f"[reframe:{record_id}] plan: {len(segments)} segments",
        extra={
            "who": "reframe",
            "where": "_plan_and_evaluate",
            "what": f"segments={len(segments)}",
            "why": "planning_done",
            "how": "reconcile",
        },
    )
    perception = {
        **detection_backend(),
        "sample_fps": scan["det_fps"],
        "frames_expected": int(dur * scan["det_fps"]),
        "active_area": active_summary,
    }
    report = proc._store_eval_report(
        record_id,
        segments,
        scan["tracked_frames"],
        scan["person_frames"],
        scan["speaker_segments"],
        w,
        h,
        dur,
        canvas_h=out_h,
        rungs=rungs,
        perception=perception,
    )
    return segments, report


def run_ai_reframe_pipeline(
    proc: Any,
    record: Any,
    record_id: str,
    src_path: str,
    out_path: str,
    probe: dict,
    tmp: TempFileManager,
) -> None:
    """v2 adaptive letterbox: cuts -> detect -> Gemini -> plan -> smooth -> render."""
    from reframe_service import render_plan

    has_audio = probe.get("has_audio", True)
    ar, out_w, out_h, rungs = _resolve_canvas_and_rungs(record)
    logger.info(
        f"[reframe:{record_id}] output {ar} ({out_w}x{out_h})",
        extra={
            "who": "reframe",
            "where": "_run_ai_reframe",
            "what": f"ar={ar},{out_w}x{out_h}",
            "why": "start_ai_reframe",
            "how": "OUTPUT_CANVAS",
        },
    )
    scan = proc._detect_and_scan(record, record_id, src_path, probe, ar, tmp)
    segments, report = proc._plan_and_evaluate(
        record, record_id, scan, probe, out_h, rungs
    )
    w, h = scan["w"], scan["h"]
    proc.update_status(record_id, "processing", 50)
    render_plan(
        src_path=src_path,
        out_path=out_path,
        segments=segments,
        src_w=w,
        src_h=h,
        has_audio=has_audio,
        out_w=out_w,
        out_h=out_h,
        src_crop=scan["src_crop"],
        full_src_wh=(probe["width"], probe["height"]),
    )
    proc._store_render_check(record_id, report, out_path, segments, w, h, out_w, out_h)

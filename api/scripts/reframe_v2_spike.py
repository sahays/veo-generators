#!/usr/bin/env python3
"""THROWAWAY validation spike for reframe v2 adaptive letterboxing (Phase 0.5).

Gate before building Phase 1. Runs the full v2 decision path on a LOCAL clip and
emits diagnostic and adaptive-letterboxed videos for human review.
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ffmpeg_runner import _FILTER_PLACEHOLDER, ffprobe_video, run_ffmpeg_with_filter
from mediapipe_detection import scan_video_faces, track_faces
from reframe_diagnostic import render_diagnostic
from reframe_filters import build_canvas_filter
from reframe_plan import reconcile
from reframe_service import _concat_chunks, _safe_unlink
from scene_detect import detect_cuts

logger = logging.getLogger("reframe_v2_spike")


def _log(msg: str, where: str = "reframe_v2_spike") -> None:
    logger.info(
        msg,
        extra={
            "who": "reframe_v2_spike",
            "where": where,
            "what": msg[:120],
            "why": "Reframe v2 validation spike",
            "how": "cli",
        },
    )


def _maybe_gemini_scenes(gcs_uri: str, content_type: str, track_summary: str) -> list:
    """Call Gemini scene analysis if a GCS URI + app deps are available."""
    if not gcs_uri:
        return []
    try:
        import asyncio

        import deps

        deps.init_services()
        result = asyncio.new_event_loop().run_until_complete(
            deps.ai_svc.analyze_video_scenes(
                gcs_uri=gcs_uri,
                mime_type="video/mp4",
                content_type=content_type,
                chirp_context=track_summary,
            )
        )
        return result.data.get("scenes", [])
    except Exception as e:  # noqa: BLE001 — spike: degrade to face-only
        _log(
            f"[spike] Gemini unavailable ({e}); running face-only",
            "_maybe_gemini_scenes",
        )
        return []


def _render_segment(src: str, out: str, seg: dict, src_w: int, src_h: int) -> None:
    """Render one segment with the unified canvas filter (re-encodes audio for sync)."""
    ss, dur = seg["start"], seg["end"] - seg["start"]
    kps = [(t - ss, x, y) for (t, x, y) in seg["crops"][0]["keypoints"]]
    filt = build_canvas_filter(kps, src_w, src_h, tuple(seg["inner_ar"]))
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{ss:.3f}",
        "-i",
        src,
        "-t",
        f"{dur:.3f}",
        _FILTER_PLACEHOLDER,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        out,
    ]
    run_ffmpeg_with_filter(cmd, filt, filter_flag="-/filter_complex", label="spike-seg")


def _render_all_segments(
    video: str, base: str, plan: list, w: int, h: int, has_audio: bool
) -> None:
    seg_paths: list[str] = []
    try:
        for i, s in enumerate(plan):
            p = f"{base}.seg{i}.mp4"
            _render_segment(video, p, s, w, h)
            seg_paths.append(p)
        v2 = f"{base}.v2.mp4"
        _concat_chunks(seg_paths, v2, has_audio)
        _log(f"[spike] wrote {v2}", "_render_all_segments")
    finally:
        for p in seg_paths:
            _safe_unlink(p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="local landscape video file")
    ap.add_argument("--gcs-uri", default="", help="gs:// URI to enable Gemini labels")
    ap.add_argument("--content-type", default="other")
    ap.add_argument("--outdir", default="/tmp")
    args = ap.parse_args()

    base = os.path.join(args.outdir, os.path.splitext(os.path.basename(args.video))[0])
    probe = ffprobe_video(args.video)
    w, h, dur = probe["width"], probe["height"], probe["duration"]
    has_audio = probe.get("has_audio", True)
    _log(f"[spike] source {w}x{h} {dur:.1f}s", "main")

    cuts = detect_cuts(args.video)
    _log(f"[spike] {len(cuts)} cuts: {[round(c, 2) for c in cuts]}", "main")

    tracked = track_faces(scan_video_faces(args.video, sample_fps=0.5))
    from _reframe_helpers import format_track_summary

    track_summary = format_track_summary(tracked)
    scenes = _maybe_gemini_scenes(args.gcs_uri, args.content_type, track_summary)
    plan = reconcile(scenes, tracked, cuts, w, h, dur)
    for s in plan:
        _log(f"  [{s['start']:6.2f}-{s['end']:6.2f}] {s['reason']}", "main")

    diag = f"{base}.diag.mp4"
    render_diagnostic(
        args.video, diag, tracked, scenes, w, h, segments=plan, has_audio=has_audio
    )
    _log(f"[spike] wrote {diag}", "main")
    _render_all_segments(args.video, base, plan, w, h, has_audio)


if __name__ == "__main__":
    main()

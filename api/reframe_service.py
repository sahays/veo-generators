"""Smart video reframing — execution layer.

Renders an adaptive-letterbox segment plan with FFmpeg (per-segment filters,
parallel encode, concat, single audio mux). Filter generation lives in
reframe_filters; pan-path math in focal_path; FFmpeg/ffprobe in ffmpeg_runner.
"""

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

from ffmpeg_runner import (
    ffprobe_video,
    run_ffmpeg,
    run_ffmpeg_with_filter,
)
from reframe_filters import build_canvas_filter, build_split_filter

# Re-export for backward compatibility (workers import ffprobe_video from here)
__all__ = [
    "ffprobe_video",
    "render_plan",
]

logger = logging.getLogger(__name__)

NUM_PARALLEL_WORKERS = int(os.environ.get("FFMPEG_WORKERS", "0")) or os.cpu_count() or 4


# ---------------------------------------------------------------------------
# Adaptive letterboxing (v2) — render a per-segment plan
# ---------------------------------------------------------------------------


def render_plan(
    src_path: str,
    out_path: str,
    segments: List[dict],
    src_w: int,
    src_h: int,
    has_audio: bool = True,
    out_w: int = 1080,
    out_h: int = 1920,
) -> str:
    """Render an adaptive-letterbox plan: each segment to its own inner AR, concat.

    Boundaries are scene cuts. Segments are rendered VIDEO-ONLY and the source
    audio is muxed once at the end: re-encoding AAC per segment and stream-copy
    concatenating inserts encoder priming (~2 AAC frames) at every join, which
    pops and accumulates A/V drift across a long plan (~36 joins on 3 minutes).
    The video timeline tiles [0, duration] exactly, so a single encode of the
    original track stays in sync by construction. `out_w`×`out_h` is the output
    canvas (default 9:16 1080×1920; pass 1080×1440 for 3:4).
    """
    if not segments:
        raise ValueError("render_plan: empty plan")

    seg_paths = [
        tempfile.mkstemp(suffix=f"_seg{i}.mp4")[1] for i in range(len(segments))
    ]
    video_path = tempfile.mkstemp(suffix="_video.mp4")[1] if has_audio else out_path
    workers = min(len(segments), NUM_PARALLEL_WORKERS)
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _render_segment,
                    src_path,
                    seg_paths[i],
                    seg,
                    src_w,
                    src_h,
                    False,  # video-only; audio muxed once below
                    out_w,
                    out_h,
                ): i
                for i, seg in enumerate(segments)
            }
            for f in as_completed(futures):
                f.result()
                logger.info(f"Segment {futures[f] + 1}/{len(segments)} rendered")
        _concat_chunks(seg_paths, video_path, has_audio=False)
        if has_audio:
            _mux_source_audio(video_path, src_path, out_path)
        return out_path
    finally:
        for p in seg_paths:
            _safe_unlink(p)
        if has_audio:
            _safe_unlink(video_path)


def _concat_chunks(chunk_paths: list, out_path: str, has_audio: bool) -> str:
    """Concatenate rendered segments using the concat demuxer with -c copy."""
    fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_concat_")
    try:
        with os.fdopen(fd, "w") as f:
            for p in chunk_paths:
                f.write(f"file '{p}'\n")
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
        ]
        cmd += ["-an"] if not has_audio else []
        cmd += ["-movflags", "+faststart", out_path]
        run_ffmpeg(cmd, timeout=300, label="concat-chunks")
        return out_path
    finally:
        _safe_unlink(list_path)


def _mux_source_audio(video_path: str, src_path: str, out_path: str) -> str:
    """Mux the ORIGINAL source audio onto the concatenated canvas in one pass."""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-i",
        src_path,
        "-map",
        "0:v",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        out_path,
    ]
    run_ffmpeg(cmd, timeout=600, label="mux-audio")
    return out_path


def _render_segment(
    src_path, out_path, seg, src_w, src_h, has_audio, out_w=1080, out_h=1920
) -> str:
    """Render one plan segment with the unified canvas filter (or vstack split)."""
    ss = seg["start"]
    dur = seg["end"] - ss

    def _local(crop):
        # Rebase keypoints to segment-local time (filter `t` resets after -ss seek).
        return [(t - ss, x, y) for (t, x, y) in crop["keypoints"]]

    if seg["layout"] == "split" and len(seg["crops"]) == 2:
        top, bot = seg["crops"]
        filter_str = build_split_filter(
            _local(top), _local(bot), src_w, src_h, out_w, out_h
        )
    else:
        filter_str = build_canvas_filter(
            _local(seg["crops"][0]), src_w, src_h, tuple(seg["inner_ar"]), out_w, out_h
        )
    cmd = _build_canvas_cmd(src_path, out_path, ss, dur, has_audio)
    run_ffmpeg_with_filter(
        cmd, filter_str, filter_flag="-/filter_complex", label="reframe-seg"
    )
    return out_path


def _build_canvas_cmd(src_path, out_path, ss, dur, has_audio) -> list:
    """FFmpeg command for one canvas segment (filter spliced in by the runner)."""
    from ffmpeg_runner import _FILTER_PLACEHOLDER

    parts = [
        ["ffmpeg", "-y"],
        ["-ss", f"{ss:.3f}"] if ss > 0 else [],
        ["-i", src_path],
        ["-t", f"{dur:.3f}"],
        [_FILTER_PLACEHOLDER],
        ["-map", "[v]"],
        ["-map", "0:a?", "-c:a", "aac"] if has_audio else ["-an"],
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"],
        ["-movflags", "+faststart", out_path],
    ]
    return [arg for part in parts for arg in part]


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

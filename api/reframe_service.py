"""Smart video reframing — execution layer.

Orchestrates FFmpeg cropping/panning using focal-path keypoints.
Filter generation lives in reframe_filters; smoothing in focal_path;
FFmpeg/ffprobe in ffmpeg_runner.
"""

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from ffmpeg_runner import (
    ffprobe_video,
    run_ffmpeg,
    run_ffmpeg_with_filter,
)
from focal_path import smooth_focal_path
from reframe_filters import (
    build_blurred_bg_filter,
    build_crop_filter,
    build_vertical_split_filter,
)

# Re-export for backward compatibility (workers import from here)
__all__ = [
    "ffprobe_video",
    "smooth_focal_path",
    "execute_reframe",
    "execute_vertical_split",
]

logger = logging.getLogger(__name__)

MAX_KEYPOINTS_PER_CHUNK = 80
NUM_PARALLEL_WORKERS = int(os.environ.get("FFMPEG_WORKERS", "0")) or os.cpu_count() or 4


# ---------------------------------------------------------------------------
# Vertical split
# ---------------------------------------------------------------------------


def execute_vertical_split(
    src_path: str,
    out_path: str,
    src_w: int,
    src_h: int,
    has_audio: bool = True,
) -> str:
    """Split landscape video into two halves stacked vertically."""
    from ffmpeg_runner import _FILTER_PLACEHOLDER

    logger.info(f"Vertical split: {src_w}x{src_h}, audio: {has_audio}")
    parts = [
        ["ffmpeg", "-y", "-i", src_path],
        [_FILTER_PLACEHOLDER],
        ["-map", "[v]", "-map", "0:a?"],
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"],
        ["-c:a", "copy"] if has_audio else ["-an"],
        ["-movflags", "+faststart", out_path],
    ]
    cmd = [arg for part in parts for arg in part]
    run_ffmpeg_with_filter(
        cmd,
        build_vertical_split_filter(src_w, src_h),
        filter_flag="-/filter_complex",
        label="vertical-split",
    )
    return out_path


# ---------------------------------------------------------------------------
# Smart reframe (crop + pan)
# ---------------------------------------------------------------------------


def execute_reframe(
    src_path: str,
    out_path: str,
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    has_audio: bool = True,
    blurred_bg: bool = False,
) -> str:
    """Crop and scale video with dynamic panning. Chunks if needed."""
    chunks = _split_keypoints_into_chunks(keypoints)
    if len(chunks) == 1:
        return _execute_reframe_chunk(
            src_path,
            out_path,
            keypoints,
            src_w,
            src_h,
            has_audio,
            blurred_bg,
        )

    logger.info(f"Chunking: {len(keypoints)} keypoints -> {len(chunks)} chunks")
    chunk_paths = _process_chunks_parallel(
        chunks,
        src_path,
        src_w,
        src_h,
        has_audio,
        blurred_bg,
    )
    try:
        _concat_chunks(chunk_paths, out_path, has_audio)
        return out_path
    finally:
        for p in chunk_paths:
            _safe_unlink(p)


def _process_chunks_parallel(
    chunks,
    src_path,
    src_w,
    src_h,
    has_audio,
    blurred_bg,
) -> List[str]:
    """Process reframe chunks in parallel, return ordered output paths."""
    chunk_paths = []
    chunk_args = []
    for i, kps in enumerate(chunks):
        path = tempfile.mkstemp(suffix=f"_chunk{i}.mp4")[1]
        chunk_paths.append(path)
        ss = kps[0][0] if kps[0][0] > 0 else None
        dur = (kps[-1][0] - kps[0][0]) if i < len(chunks) - 1 else None
        chunk_args.append(
            dict(
                src_path=src_path,
                out_path=path,
                keypoints=kps,
                src_w=src_w,
                src_h=src_h,
                has_audio=has_audio,
                blurred_bg=blurred_bg,
                ss_time=ss,
                duration=dur,
            )
        )

    workers = min(len(chunks), NUM_PARALLEL_WORKERS)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_execute_reframe_chunk, **a): i
            for i, a in enumerate(chunk_args)
        }
        for f in as_completed(futures):
            f.result()
            logger.info(f"Chunk {futures[f] + 1}/{len(chunks)} complete")
    return chunk_paths


def _execute_reframe_chunk(
    src_path: str,
    out_path: str,
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    has_audio: bool = True,
    blurred_bg: bool = False,
    ss_time: float | None = None,
    duration: float | None = None,
) -> str:
    """Process a single reframe chunk (or full video if no chunking)."""
    if ss_time and ss_time > 0:
        keypoints = [(t - ss_time, x, y) for t, x, y in keypoints]

    filter_str = (
        build_blurred_bg_filter(keypoints, src_w, src_h)
        if blurred_bg
        else build_crop_filter(keypoints, src_w, src_h)
    )
    cmd = _build_reframe_cmd(
        src_path, out_path, ss_time, duration, has_audio, blurred_bg
    )
    flag = "-/filter_complex" if blurred_bg else "-/filter:v"
    run_ffmpeg_with_filter(cmd, filter_str, filter_flag=flag, label="reframe-chunk")
    return out_path


def _build_reframe_cmd(
    src_path, out_path, ss_time, duration, has_audio, blurred_bg
) -> list:
    """Build the FFmpeg command for a reframe chunk (without filter args)."""
    from ffmpeg_runner import _FILTER_PLACEHOLDER

    parts = [
        ["ffmpeg", "-y"],
        ["-ss", f"{ss_time:.3f}"] if ss_time else [],
        ["-i", src_path],
        ["-t", f"{duration:.3f}"] if duration else [],
        [_FILTER_PLACEHOLDER],
        ["-map", "[v]", "-map", "0:a?"] if blurred_bg else [],
        ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"],
        ["-c:a", "copy"] if has_audio else ["-an"],
        ["-movflags", "+faststart", out_path],
    ]
    return [arg for part in parts for arg in part]


def _concat_chunks(chunk_paths: list, out_path: str, has_audio: bool) -> str:
    """Concatenate reframe chunks using concat demuxer with -c copy."""
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


# ---------------------------------------------------------------------------
# Keypoint chunking helpers
# ---------------------------------------------------------------------------


def _interpolate_keypoint(
    keypoints: List[Tuple[float, float, float]],
    t: float,
) -> Tuple[float, float, float]:
    """Linearly interpolate x,y at time t between surrounding keypoints."""
    import bisect

    if t <= keypoints[0][0]:
        return keypoints[0]
    if t >= keypoints[-1][0]:
        return keypoints[-1]
    times = [kp[0] for kp in keypoints]
    i = min(bisect.bisect_right(times, t) - 1, len(keypoints) - 2)
    t0, x0, y0 = keypoints[i]
    t1, x1, y1 = keypoints[i + 1]
    frac = (t - t0) / (t1 - t0) if t1 != t0 else 0
    return (t, x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)


def _split_keypoints_into_chunks(
    keypoints: List[Tuple[float, float, float]],
    max_per_chunk: int = MAX_KEYPOINTS_PER_CHUNK,
    num_workers: int = NUM_PARALLEL_WORKERS,
) -> List[List[Tuple[float, float, float]]]:
    """Split keypoints into chunks for parallel processing."""
    total_dur = keypoints[-1][0] - keypoints[0][0]
    chunks_for_depth = max(
        1, (len(keypoints) + max_per_chunk - 2) // (max_per_chunk - 1)
    )
    num_chunks = max(chunks_for_depth, num_workers)
    if num_chunks <= 1:
        return [keypoints]

    chunk_dur = total_dur / num_chunks
    start = keypoints[0][0]
    boundaries = [start + i * chunk_dur for i in range(num_chunks)]
    boundaries.append(keypoints[-1][0])

    chunks = []
    for ci in range(len(boundaries) - 1):
        c_start, c_end = boundaries[ci], boundaries[ci + 1]
        kps = [kp for kp in keypoints if c_start <= kp[0] <= c_end]
        if not kps or kps[0][0] > c_start:
            kps.insert(0, _interpolate_keypoint(keypoints, c_start))
        if kps[-1][0] < c_end:
            kps.append(_interpolate_keypoint(keypoints, c_end))
        chunks.append(kps)
    return chunks


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

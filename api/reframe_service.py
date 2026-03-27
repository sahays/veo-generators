"""Pure computation module for smart video reframing.

Handles focal point interpolation, FFmpeg filter generation, and video processing.
No FastAPI or Firestore dependencies — easily testable.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import List, Tuple

logger = logging.getLogger(__name__)

MAX_KEYPOINTS_PER_CHUNK = 80


def ffprobe_video(path: str) -> dict:
    """Extract width, height, fps, and duration from a video file."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    logger.info(f"Running ffprobe on: {path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        logger.error(f"ffprobe stderr: {result.stderr}")
        raise RuntimeError(
            f"ffprobe failed (exit {result.returncode}): {result.stderr}"
        )

    data = json.loads(result.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s["codec_type"] == "video"), None
    )
    if not video_stream:
        logger.error(
            f"ffprobe found no video stream. Streams: {[s.get('codec_type') for s in data.get('streams', [])]}"
        )
        raise RuntimeError("No video stream found in source file")

    # Parse fps from r_frame_rate (e.g. "30/1")
    fps_parts = video_stream.get("r_frame_rate", "30/1").split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0

    duration = float(data.get("format", {}).get("duration", 0))
    if duration == 0:
        duration = float(video_stream.get("duration", 0))

    has_audio = any(s["codec_type"] == "audio" for s in data.get("streams", []))

    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "fps": fps,
        "duration": duration,
        "has_audio": has_audio,
    }


def _cubic_hermite(t: float, p0: float, m0: float, p1: float, m1: float) -> float:
    """Cubic Hermite interpolation between two points."""
    t2 = t * t
    t3 = t2 * t
    return (
        (2 * t3 - 3 * t2 + 1) * p0
        + (t3 - 2 * t2 + t) * m0
        + (-2 * t3 + 3 * t2) * p1
        + (t3 - t2) * m1
    )


def _compute_tangents(times: List[float], values: List[float]) -> List[float]:
    """Compute Catmull-Rom tangents for a sequence of points."""
    n = len(values)
    tangents = [0.0] * n
    for i in range(n):
        if i == 0:
            if n > 1:
                dt = times[1] - times[0]
                tangents[i] = (values[1] - values[0]) / dt if dt > 0 else 0.0
            else:
                tangents[i] = 0.0
        elif i == n - 1:
            dt = times[i] - times[i - 1]
            tangents[i] = (values[i] - values[i - 1]) / dt if dt > 0 else 0.0
        else:
            dt = times[i + 1] - times[i - 1]
            tangents[i] = (values[i + 1] - values[i - 1]) / dt if dt > 0 else 0.0
    return tangents


def _interpolate_segment(
    times: List[float], values: List[float], eval_times: List[float]
) -> List[float]:
    """Interpolate values at eval_times using cubic Hermite splines."""
    if len(times) < 2:
        return [values[0]] * len(eval_times) if values else [0.5] * len(eval_times)

    tangents = _compute_tangents(times, values)
    result = []

    for t in eval_times:
        # Clamp to range
        if t <= times[0]:
            result.append(values[0])
            continue
        if t >= times[-1]:
            result.append(values[-1])
            continue

        # Find segment
        seg = 0
        for i in range(len(times) - 1):
            if times[i] <= t <= times[i + 1]:
                seg = i
                break

        dt = times[seg + 1] - times[seg]
        if dt == 0:
            result.append(values[seg])
            continue

        local_t = (t - times[seg]) / dt
        val = _cubic_hermite(
            local_t,
            values[seg],
            tangents[seg] * dt,
            values[seg + 1],
            tangents[seg + 1] * dt,
        )
        result.append(val)

    return result


def smooth_focal_path(
    focal_points: List[dict],
    scene_changes: List[dict],
    duration: float,
    fps: float,
    max_velocity: float = 0.15,
    deadzone: float = 0.05,
) -> List[Tuple[float, float, float]]:
    """Smooth focal points into a pan path with keypoints at ~1/sec.

    Args:
        focal_points: List of {time_sec, x, y} dicts from Gemini.
        scene_changes: List of {time_sec} dicts for hard cuts.
        duration: Video duration in seconds.
        fps: Video frame rate.
        max_velocity: Max pan speed as fraction of frame width per second.
        deadzone: Suppress movements smaller than this fraction.

    Returns:
        List of (time_sec, x_fraction, y_fraction) keypoints at ~1/sec.
    """
    if not focal_points:
        # Center crop fallback
        return [(0.0, 0.5, 0.5), (duration, 0.5, 0.5)]

    # Sort focal points by time, clamp to video duration
    sorted_pts = sorted(focal_points, key=lambda p: p["time_sec"])
    sorted_pts = [p for p in sorted_pts if p["time_sec"] <= duration]
    if not sorted_pts:
        return [(0.0, 0.5, 0.5), (duration, 0.5, 0.5)]

    # Build scene-change boundaries, clamp to video duration
    valid_cuts = [sc["time_sec"] for sc in scene_changes if sc["time_sec"] <= duration]
    cuts = sorted(set([0.0] + valid_cuts + [duration]))

    # Split focal points into segments by scene boundaries
    segments = []
    for i in range(len(cuts) - 1):
        seg_start, seg_end = cuts[i], cuts[i + 1]
        seg_pts = [p for p in sorted_pts if seg_start <= p["time_sec"] <= seg_end]
        if not seg_pts:
            # No focal points in this segment — use nearest
            nearest = min(
                sorted_pts, key=lambda p: abs(p["time_sec"] - (seg_start + seg_end) / 2)
            )
            seg_pts = [{"time_sec": seg_start, "x": nearest["x"], "y": nearest["y"]}]
        segments.append((seg_start, seg_end, seg_pts))

    # Interpolate each segment independently
    all_keypoints = []
    for seg_start, seg_end, seg_pts in segments:
        seg_duration = seg_end - seg_start
        if seg_duration <= 0:
            continue

        # Eval at 1-second intervals within segment
        step = 1.0 if seg_duration > 2 else max(0.5, seg_duration)
        eval_times = []
        t = seg_start
        while t < seg_end:
            eval_times.append(t)
            t += step
        eval_times.append(seg_end)

        times = [p["time_sec"] for p in seg_pts]
        x_vals = [max(0.0, min(1.0, p["x"])) for p in seg_pts]
        y_vals = [max(0.0, min(1.0, p["y"])) for p in seg_pts]

        interp_x = _interpolate_segment(times, x_vals, eval_times)
        interp_y = _interpolate_segment(times, y_vals, eval_times)

        for t, x, y in zip(eval_times, interp_x, interp_y):
            all_keypoints.append((t, max(0.0, min(1.0, x)), max(0.0, min(1.0, y))))

    # Remove duplicate times (at segment boundaries)
    seen_times = set()
    deduped = []
    for kp in all_keypoints:
        t_rounded = round(kp[0], 3)
        if t_rounded not in seen_times:
            seen_times.add(t_rounded)
            deduped.append(kp)

    # Apply velocity limiting
    if len(deduped) > 1:
        limited = [deduped[0]]
        for i in range(1, len(deduped)):
            dt = deduped[i][0] - limited[-1][0]
            if dt <= 0:
                limited.append(deduped[i])
                continue

            dx = deduped[i][1] - limited[-1][1]
            max_dx = max_velocity * dt

            if abs(dx) > max_dx:
                clamped_x = limited[-1][1] + max_dx * (1 if dx > 0 else -1)
            else:
                clamped_x = deduped[i][1]

            # Apply deadzone — suppress small movements
            if abs(clamped_x - limited[-1][1]) < deadzone:
                clamped_x = limited[-1][1]

            limited.append(
                (deduped[i][0], max(0.0, min(1.0, clamped_x)), deduped[i][2])
            )
        deduped = limited

    # Collapse consecutive keypoints with same x value (keep first + last of each run)
    # This dramatically reduces expression size for long videos
    if len(deduped) > 2:
        collapsed = [deduped[0]]
        for i in range(1, len(deduped) - 1):
            prev_x = deduped[i - 1][1]
            curr_x = deduped[i][1]
            next_x = deduped[i + 1][1]
            # Keep if x is changing (transition point)
            if curr_x != prev_x or curr_x != next_x:
                collapsed.append(deduped[i])
        collapsed.append(deduped[-1])
        deduped = collapsed

    logger.info(
        f"smooth_focal_path: {len(deduped)} final keypoints for {duration:.1f}s video"
    )
    return deduped


def build_crop_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
) -> str:
    """Generate FFmpeg crop + scale filter string for dynamic panning.

    The crop extracts a 9:16 window from the source, then scales to 1080x1920.
    X-offset is a piecewise-linear function of time using nested if() expressions.
    """
    crop_w = int(src_h * 9 / 16)
    crop_h = src_h
    max_x = src_w - crop_w

    if max_x <= 0:
        # Source is already narrower than 9:16 — just scale
        return "scale=1080:1920"

    # Convert fractional x to pixel offsets (ensure native Python types)
    pixel_keypoints = []
    for t, x_frac, _ in keypoints:
        center_px = float(x_frac) * src_w
        left_px = center_px - crop_w / 2
        left_px = max(0, min(max_x, left_px))
        pixel_keypoints.append((float(t), int(left_px)))

    if not pixel_keypoints:
        center_x = max(0, (src_w - crop_w) // 2)
        return f"crop={crop_w}:{crop_h}:{center_x}:0,scale=1080:1920"

    if len(pixel_keypoints) == 1:
        return f"crop={crop_w}:{crop_h}:{pixel_keypoints[0][1]}:0,scale=1080:1920"

    x_expr = _build_piecewise_linear_expr(pixel_keypoints)

    # Clamp expression to valid range using FFmpeg's clip() function
    return f"crop={crop_w}:{crop_h}:clip({x_expr}\\,0\\,{max_x}):0,scale=1080:1920"


def _build_piecewise_linear_expr(keypoints: List[Tuple[float, int]]) -> str:
    """Build an FFmpeg expression for piecewise-linear interpolation over time.

    For each segment between keypoints, linearly interpolates:
      x(t) = x0 + (x1 - x0) * (t - t0) / (t1 - t0)

    Uses nested if(lt(t,...)) expressions.
    """
    if len(keypoints) == 1:
        return str(keypoints[0][1])

    # Build from the last segment backward (innermost = last value)
    expr = str(keypoints[-1][1])

    for i in range(len(keypoints) - 2, -1, -1):
        t0, x0 = keypoints[i]
        t1, x1 = keypoints[i + 1]

        if t1 == t0:
            segment_expr = str(x0)
        else:
            # Linear interpolation: x0 + (x1 - x0) * (t - t0) / (t1 - t0)
            dx = x1 - x0
            dt = t1 - t0
            if dx == 0:
                segment_expr = str(x0)
            else:
                segment_expr = f"{x0}+{dx}*(t-{t0:.3f})/{dt:.3f}"

        expr = f"if(lt(t\\,{t1:.3f})\\,{segment_expr}\\,{expr})"

    return expr


def build_blurred_bg_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
) -> str:
    """Generate FFmpeg filter_complex for blurred background + wider smart crop.

    Layout (1080x1920 output):
    - 10% top: blurred version of source
    - 80% middle: smart-cropped content (wider ~4:5 ratio with subject tracking)
    - 10% bottom: blurred version of source

    The crop is wider than pure 9:16, so more of the scene is visible.
    """
    # Content area: 80% of 1920 = 1536px tall, 1080 wide
    fg_h = 1536
    overlay_y = 192  # (1920 - 1536) / 2 = 192px blur on each side

    # Crop ratio: 1080/1536 ≈ 0.703 → from source, crop_w/crop_h = 0.703
    # crop_h = full source height, crop_w = crop_h * 1080 / 1536
    crop_h = src_h
    crop_w = int(src_h * 1080 / fg_h)
    # Ensure crop_w doesn't exceed source width
    crop_w = min(crop_w, src_w)
    max_x = src_w - crop_w

    # Background: scale source to fill 1080x1920, blur heavily
    bg_filter = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=40[bg]"
    )

    if max_x <= 0 or not keypoints:
        return (
            f"{bg_filter};[0:v]scale=1080:{fg_h}[fg];[bg][fg]overlay=0:{overlay_y}[v]"
        )

    # Build crop expression using focal points (ensure native Python types)
    pixel_keypoints = []
    for t, x_frac, _ in keypoints:
        center_px = float(x_frac) * src_w
        left_px = center_px - crop_w / 2
        left_px = max(0, min(max_x, left_px))
        pixel_keypoints.append((float(t), int(left_px)))

    if len(pixel_keypoints) <= 1:
        x_val = (
            pixel_keypoints[0][1] if pixel_keypoints else max(0, (src_w - crop_w) // 2)
        )
        return (
            f"{bg_filter};"
            f"[0:v]crop={crop_w}:{crop_h}:{x_val}:0,scale=1080:{fg_h}[fg];"
            f"[bg][fg]overlay=0:{overlay_y}[v]"
        )

    x_expr = _build_piecewise_linear_expr(pixel_keypoints)

    # Clamp expression to valid range
    return (
        f"{bg_filter};"
        f"[0:v]crop={crop_w}:{crop_h}:clip({x_expr}\\,0\\,{max_x}):0[cropped];"
        f"[cropped]scale=1080:{fg_h}[fg];"
        f"[bg][fg]overlay=0:{overlay_y}[v]"
    )


def execute_reframe(
    src_path: str,
    out_path: str,
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    has_audio: bool = True,
    blurred_bg: bool = False,
) -> str:
    """Run FFmpeg to crop and scale video with dynamic panning.

    When keypoints exceed MAX_KEYPOINTS_PER_CHUNK, the video is split into
    time-range chunks (each with ≤80 keypoints), processed independently,
    and concatenated with -c copy.
    """
    chunks = _split_keypoints_into_chunks(keypoints)

    if len(chunks) == 1:
        return _execute_reframe_chunk(
            src_path, out_path, keypoints, src_w, src_h, has_audio, blurred_bg
        )

    logger.info(
        f"Chunking: {len(keypoints)} keypoints -> {len(chunks)} chunks "
        f"(max {MAX_KEYPOINTS_PER_CHUNK} per chunk)"
    )

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Prepare chunk args
    chunk_args: list[dict] = []
    chunk_paths: list[str] = []
    for i, chunk_kps in enumerate(chunks):
        chunk_start = chunk_kps[0][0]
        chunk_end = chunk_kps[-1][0]

        fd, chunk_path = tempfile.mkstemp(suffix=f"_chunk{i}.mp4")
        os.close(fd)
        chunk_paths.append(chunk_path)

        ss_time = chunk_start if chunk_start > 0 else None
        duration = (chunk_end - chunk_start) if i < len(chunks) - 1 else None

        chunk_args.append(
            dict(
                src_path=src_path,
                out_path=chunk_path,
                keypoints=chunk_kps,
                src_w=src_w,
                src_h=src_h,
                has_audio=has_audio,
                blurred_bg=blurred_bg,
                ss_time=ss_time,
                duration=duration,
            )
        )
        logger.info(
            f"Chunk {i + 1}/{len(chunks)}: "
            f"t={chunk_start:.1f}-{chunk_end:.1f}s, "
            f"{len(chunk_kps)} keypoints"
        )

    # Process chunks in parallel
    try:
        max_workers = min(len(chunks), NUM_PARALLEL_WORKERS)
        logger.info(
            f"Processing {len(chunks)} chunks with {max_workers} parallel workers"
        )
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_execute_reframe_chunk, **args): i
                for i, args in enumerate(chunk_args)
            }
            for future in as_completed(futures):
                idx = futures[future]
                future.result()  # raises if chunk failed
                logger.info(f"Chunk {idx + 1}/{len(chunks)} complete")

        logger.info(f"Concatenating {len(chunks)} chunks...")
        _concat_reframe_chunks(chunk_paths, out_path, has_audio)
        logger.info(f"Chunked reframe complete: {out_path}")
        return out_path

    finally:
        for p in chunk_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


NUM_PARALLEL_WORKERS = int(os.environ.get("FFMPEG_WORKERS", "0")) or os.cpu_count() or 4


def _interpolate_keypoint(
    keypoints: List[Tuple[float, float, float]], t: float
) -> Tuple[float, float, float]:
    """Linearly interpolate x,y at time t between surrounding keypoints."""
    if t <= keypoints[0][0]:
        return keypoints[0]
    if t >= keypoints[-1][0]:
        return keypoints[-1]
    for i in range(len(keypoints) - 1):
        t0, x0, y0 = keypoints[i]
        t1, x1, y1 = keypoints[i + 1]
        if t0 <= t <= t1:
            if t1 == t0:
                return (t, x0, y0)
            frac = (t - t0) / (t1 - t0)
            return (t, x0 + (x1 - x0) * frac, y0 + (y1 - y0) * frac)
    return keypoints[-1]


def _split_keypoints_into_chunks(
    keypoints: List[Tuple[float, float, float]],
    max_per_chunk: int = MAX_KEYPOINTS_PER_CHUNK,
    num_workers: int = NUM_PARALLEL_WORKERS,
) -> List[List[Tuple[float, float, float]]]:
    """Split keypoints into chunks — one per vCPU for maximum parallelism.

    Also respects max_per_chunk to stay under FFmpeg's expression depth limit.
    Interpolates boundary keypoints so crop position is continuous.
    """
    total_duration = keypoints[-1][0] - keypoints[0][0]

    # Determine target chunk count: at least num_workers, more if keypoints demand it
    chunks_for_depth = max(
        1, (len(keypoints) + max_per_chunk - 2) // (max_per_chunk - 1)
    )
    num_chunks = max(chunks_for_depth, num_workers)

    if num_chunks <= 1:
        return [keypoints]

    chunk_duration = total_duration / num_chunks

    # Build time boundaries
    start_time = keypoints[0][0]
    chunk_boundaries = [start_time + i * chunk_duration for i in range(num_chunks)]
    chunk_boundaries.append(keypoints[-1][0])

    # Build chunks with interpolated boundary keypoints
    chunks = []
    for ci in range(len(chunk_boundaries) - 1):
        c_start = chunk_boundaries[ci]
        c_end = chunk_boundaries[ci + 1]

        chunk_kps = [kp for kp in keypoints if c_start <= kp[0] <= c_end]

        if not chunk_kps or chunk_kps[0][0] > c_start:
            chunk_kps.insert(0, _interpolate_keypoint(keypoints, c_start))
        if chunk_kps[-1][0] < c_end:
            chunk_kps.append(_interpolate_keypoint(keypoints, c_end))

        chunks.append(chunk_kps)

    return chunks


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
    """Process a single reframe chunk (or the full video if no chunking)."""
    # Time-shift keypoints so filter expressions start at t=0
    if ss_time is not None and ss_time > 0:
        keypoints = [(t - ss_time, x, y) for t, x, y in keypoints]

    if blurred_bg:
        filter_str = build_blurred_bg_filter(keypoints, src_w, src_h)
        use_complex = True
    else:
        filter_str = build_crop_filter(keypoints, src_w, src_h)
        use_complex = False

    logger.info(
        f"Source: {src_w}x{src_h}, keypoints: {len(keypoints)}, "
        f"audio: {has_audio}, blurred_bg: {blurred_bg}"
    )

    fd, filter_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_filter_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(filter_str)

        cmd = ["ffmpeg", "-y"]
        if ss_time is not None and ss_time > 0:
            cmd += ["-ss", f"{ss_time:.3f}"]
        cmd += ["-i", src_path]
        if duration is not None:
            cmd += ["-t", f"{duration:.3f}"]

        if use_complex:
            cmd += ["-/filter_complex", filter_path, "-map", "[v]", "-map", "0:a?"]
        else:
            cmd += ["-/filter:v", filter_path]

        cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "23"]
        if has_audio:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", out_path]

        logger.info(f"FFmpeg cmd: {' '.join(cmd[:10])}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)

        if result.returncode != 0:
            stderr_tail = result.stderr[-1000:] if result.stderr else "(no stderr)"
            logger.error(f"FFmpeg returncode={result.returncode}")
            logger.error(f"FFmpeg stderr: {stderr_tail}")
            raise RuntimeError(
                f"FFmpeg failed (exit {result.returncode}): {stderr_tail}"
            )

        return out_path

    finally:
        try:
            os.unlink(filter_path)
        except OSError:
            pass


def _concat_reframe_chunks(
    chunk_paths: list[str], out_path: str, has_audio: bool
) -> str:
    """Concatenate reframe chunks using the concat demuxer with -c copy."""
    fd, list_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_concat_")
    try:
        with os.fdopen(fd, "w") as f:
            for path in chunk_paths:
                f.write(f"file '{path}'\n")

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
        if not has_audio:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", out_path]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
            raise RuntimeError(f"Chunk concat failed: {stderr_tail}")

        return out_path
    finally:
        try:
            os.unlink(list_path)
        except OSError:
            pass

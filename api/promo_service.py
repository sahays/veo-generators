"""Pure computation module for promo generation.

Handles video segment extraction and concatenation with cross-dissolve transitions.
No FastAPI or Firestore dependencies.
"""

import logging
import os
import subprocess
import tempfile
from typing import List

logger = logging.getLogger(__name__)


def parse_timestamp(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = ts.strip().split(":")
    parts = [float(p) for p in parts]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def extract_segment(
    src_path: str, out_path: str, start_sec: float, end_sec: float
) -> str:
    """Extract a segment from a video using FFmpeg.

    Uses -ss before -i for fast seeking, then -t for duration.
    Returns the output path.
    """
    duration = end_sec - start_sec
    if duration <= 0:
        raise ValueError(f"Invalid segment: start={start_sec}, end={end_sec}")

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        src_path,
        "-t",
        f"{duration:.3f}",
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
        out_path,
    ]

    logger.info(
        f"Extracting segment: {start_sec:.1f}s - {end_sec:.1f}s ({duration:.1f}s)"
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"FFmpeg extract failed: {stderr_tail}")
        raise RuntimeError(f"Segment extraction failed: {stderr_tail}")

    return out_path


def concatenate_with_crossfade(
    segment_paths: List[str],
    out_path: str,
    crossfade_duration: float = 0.5,
) -> str:
    """Concatenate video segments with cross-dissolve transitions.

    Uses FFmpeg xfade (video) and acrossfade (audio) filters.
    Writes filter graph to a temp file to avoid escaping issues.
    Returns the output path.
    """
    if not segment_paths:
        raise ValueError("No segments to concatenate")

    if len(segment_paths) == 1:
        # Single segment — just copy
        import shutil

        shutil.copy2(segment_paths[0], out_path)
        return out_path

    # Get duration of each segment for xfade offset calculation
    durations = []
    for p in segment_paths:
        dur = _get_duration(p)
        durations.append(dur)
        logger.info(f"Segment {p}: {dur:.2f}s")

    # Probe first segment to get target resolution for normalization
    import json as _json

    probe_cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        segment_paths[0],
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
    target_w, target_h = 1280, 720  # fallback
    if probe_result.returncode == 0:
        probe_data = _json.loads(probe_result.stdout)
        vs = next(
            (s for s in probe_data.get("streams", []) if s["codec_type"] == "video"),
            None,
        )
        if vs:
            target_w = int(vs["width"])
            target_h = int(vs["height"])
            # Ensure even dimensions
            target_w = target_w // 2 * 2
            target_h = target_h // 2 * 2
    logger.info(f"Crossfade target resolution: {target_w}x{target_h}")

    # Normalize all inputs to same resolution + pixel format before xfade
    norm_filters = []
    for i in range(len(segment_paths)):
        norm_filters.append(
            f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p[n{i}]"
        )

    # Build xfade filter graph with sequential labels: vx0, vx1, vx2...
    video_filters = []
    audio_filters = []

    # First pair: [n0][n1] -> [vx0]
    offset = durations[0] - crossfade_duration
    video_filters.append(
        f"[n0][n1]xfade=transition=fade:duration={crossfade_duration}:offset={offset:.3f}[vx0]"
    )
    audio_filters.append(f"[0:a][1:a]acrossfade=d={crossfade_duration}[ax0]")

    # Subsequent pairs: [vxN-1][nI] -> [vxN]
    accumulated_duration = durations[0] + durations[1] - crossfade_duration
    for i in range(2, len(segment_paths)):
        step = i - 2
        offset = accumulated_duration - crossfade_duration
        video_filters.append(
            f"[vx{step}][n{i}]xfade=transition=fade:duration={crossfade_duration}:offset={offset:.3f}[vx{step + 1}]"
        )
        audio_filters.append(
            f"[ax{step}][{i}:a]acrossfade=d={crossfade_duration}[ax{step + 1}]"
        )
        accumulated_duration += durations[i] - crossfade_duration

    # Final output labels
    n = len(segment_paths)
    final_v = f"vx{n - 2}"
    final_a = f"ax{n - 2}"

    filter_graph = ";\n".join(norm_filters + video_filters + audio_filters)

    # Write filter to temp file
    fd, filter_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_xfade_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(filter_graph)
        logger.info(f"Crossfade filter written to: {filter_path}")
        logger.info(
            f"Filter graph ({len(filter_graph)} chars): {filter_graph[:300]}..."
        )

        # Build command
        cmd = ["ffmpeg", "-y"]
        for p in segment_paths:
            cmd += ["-i", p]
        cmd += [
            "-/filter_complex",
            filter_path,
            "-map",
            f"[{final_v}]",
            "-map",
            f"[{final_a}]",
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
            out_path,
        ]

        logger.info(f"Running FFmpeg crossfade with {len(segment_paths)} segments")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode != 0:
            stderr_tail = result.stderr[-1000:] if result.stderr else "(no stderr)"
            logger.error(f"FFmpeg crossfade failed: {stderr_tail}")
            logger.error(f"Filter was: {filter_graph[:500]}")
            raise RuntimeError(f"Crossfade stitching failed: {stderr_tail}")

        logger.info(f"Crossfade complete: {out_path}")
        return out_path

    finally:
        try:
            os.unlink(filter_path)
        except OSError:
            pass


def create_title_card_video(
    image_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
    duration: float = 2.5,
    fps: int = 24,
) -> str:
    """Convert a still image into a video clip with silent audio.

    Scales the image to match the source video resolution so xfade works.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-i",
        image_path,
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=44100:cl=stereo",
        "-vf",
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
        "-t",
        f"{duration:.1f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-shortest",
        "-movflags",
        "+faststart",
        out_path,
    ]

    logger.info(f"Creating title card video: {duration}s from {image_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"Title card creation failed: {stderr_tail}")
        raise RuntimeError(f"Title card creation failed: {stderr_tail}")

    return out_path


def overlay_image_on_segment(
    segment_path: str,
    overlay_path: str,
    out_path: str,
    fade_in: float = 0.3,
    hold: float = 1.5,
    fade_out: float = 0.3,
) -> str:
    """Overlay a PNG image on a video segment with fade in/out.

    The overlay appears at the start of the segment, fades in, holds, then fades out.
    """
    total = fade_in + hold + fade_out

    # Filter: scale overlay to match video, apply fade, composite
    # Write filter to file to avoid escaping issues
    # Scale overlay to match video size, apply alpha fade, composite
    filter_graph = (
        f"[1:v]scale=iw:ih,format=rgba,"
        f"fade=in:st=0:d={fade_in}:alpha=1,"
        f"fade=out:st={fade_in + hold}:d={fade_out}:alpha=1[ovr];"
        f"[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[base];"
        f"[base][ovr]overlay=W/2-w/2:H/2-h/2:enable='between(t,0,{total})',format=yuv420p"
    )

    fd, filter_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_overlay_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(filter_graph)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            segment_path,
            "-i",
            overlay_path,
            "-/filter_complex",
            filter_path,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            out_path,
        ]

        logger.info(f"Overlaying image on segment: fade_in={fade_in}, hold={hold}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
            logger.error(f"Overlay failed: {stderr_tail}")
            raise RuntimeError(f"Overlay compositing failed: {stderr_tail}")

        return out_path

    finally:
        try:
            os.unlink(filter_path)
        except OSError:
            pass


def _get_duration(path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}")

    import json

    data = json.loads(result.stdout)
    return float(data.get("format", {}).get("duration", 0))

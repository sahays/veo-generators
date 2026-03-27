"""Pure computation module for promo generation.

Handles video segment extraction and concatenation with cross-dissolve transitions.
No FastAPI or Firestore dependencies.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import List

logger = logging.getLogger(__name__)

TARGET_FPS = 30
TARGET_AUDIO_RATE = 44100


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
        "-b:a",
        "192k",
        "-ar",
        str(TARGET_AUDIO_RATE),
        "-ac",
        "2",
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

    # Validate extracted file has content
    dur = _get_duration(out_path)
    if dur <= 0:
        raise RuntimeError(
            f"Extracted segment is empty (duration={dur}): {start_sec}-{end_sec}s"
        )

    return out_path


def extract_frame(src_path: str, out_path: str, timestamp_sec: float) -> str:
    """Extract a single frame from a video at the given timestamp as a PNG."""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp_sec:.3f}",
        "-i",
        src_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        out_path,
    ]

    logger.info(f"Extracting frame at {timestamp_sec:.1f}s -> {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"Frame extraction failed: {stderr_tail}")
        raise RuntimeError(f"Frame extraction failed: {stderr_tail}")

    return out_path


def normalize_segment(
    in_path: str,
    out_path: str,
    target_w: int,
    target_h: int,
    target_fps: int = TARGET_FPS,
) -> str:
    """Re-encode a segment to canonical format for reliable crossfade.

    Forces consistent framerate, timebase, resolution, pixel format, and audio
    parameters so that xfade/acrossfade never sees mismatched inputs.
    """
    # Check if input has an audio stream
    probe_cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        in_path,
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
    has_audio = False
    if probe.returncode == 0:
        streams = json.loads(probe.stdout).get("streams", [])
        has_audio = any(s["codec_type"] == "audio" for s in streams)

    # Build video filter chain
    vf = (
        f"fps={target_fps},"
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,format=yuv420p"
    )

    cmd = ["ffmpeg", "-y", "-i", in_path]

    if not has_audio:
        # Get duration to limit synthetic audio (fallback 30s if probe fails)
        seg_dur = _get_duration(in_path)
        if seg_dur <= 0:
            seg_dur = 30.0
        cmd += [
            "-f",
            "lavfi",
            "-t",
            f"{seg_dur:.3f}",
            "-i",
            f"anullsrc=r={TARGET_AUDIO_RATE}:cl=stereo",
        ]

    cmd += [
        "-vf",
        vf,
        "-video_track_timescale",
        str(target_fps * 1000),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
    ]

    if has_audio:
        # Audio already encoded during extraction — just copy
        cmd += ["-c:a", "copy"]
    else:
        # Synthetic silent audio needs encoding
        cmd += ["-c:a", "aac", "-ar", str(TARGET_AUDIO_RATE), "-ac", "2"]

    cmd += ["-movflags", "+faststart", out_path]

    logger.info(
        f"Normalizing segment: {in_path} -> {target_w}x{target_h}@{target_fps}fps"
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"Normalize failed: {stderr_tail}")
        raise RuntimeError(f"Segment normalization failed: {stderr_tail}")

    # Validate output has a video stream
    val_cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        out_path,
    ]
    val = subprocess.run(val_cmd, capture_output=True, text=True, timeout=30)
    has_video_out = False
    if val.returncode == 0:
        for s in json.loads(val.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                has_video_out = True
                break
    if not has_video_out:
        raise RuntimeError(
            f"Normalization produced output without video stream: {out_path}"
        )

    return out_path


def concatenate_with_crossfade(
    segment_paths: List[str],
    out_path: str,
    crossfade_duration: float = 0.5,
) -> str:
    """Concatenate pre-normalized segments with cross-dissolve transitions.

    Uses pairwise stitching: each transition is an independent 2-input FFmpeg
    call. If any xfade fails, that pair falls back to a hard-cut concat.
    All segments must be pre-normalized to the same fps/resolution/format.
    """
    if not segment_paths:
        raise ValueError("No segments to concatenate")

    if len(segment_paths) == 1:
        shutil.copy2(segment_paths[0], out_path)
        return out_path

    intermediates = []
    current = segment_paths[0]

    for i in range(1, len(segment_paths)):
        is_last = i == len(segment_paths) - 1
        pair_out = out_path if is_last else _tmp_file("_pair.mp4")
        if not is_last:
            intermediates.append(pair_out)

        next_seg = segment_paths[i]
        logger.info(
            f"Stitching pair {i}/{len(segment_paths) - 1}: {current} + {next_seg}"
        )

        try:
            _xfade_pair(current, next_seg, pair_out, crossfade_duration)
        except RuntimeError:
            logger.warning(f"xfade failed for pair {i}, falling back to concat")
            # xfade may have written a corrupt file — remove before concat
            _safe_unlink(pair_out)
            _concat_pair(current, next_seg, pair_out)

        # Clean up previous intermediate (not an original segment)
        if current in intermediates:
            _safe_unlink(current)
            intermediates.remove(current)

        current = pair_out

    # Clean any remaining intermediates
    for f in intermediates:
        _safe_unlink(f)

    logger.info(f"Crossfade complete: {out_path}")
    return out_path


def _xfade_pair(
    a_path: str,
    b_path: str,
    out_path: str,
    crossfade_dur: float,
) -> None:
    """Apply xfade + acrossfade between exactly two pre-normalized segments.

    Forces fps and settb on both inputs to guarantee matching timebases,
    and on the output to keep the chain stable for subsequent pairs.
    """
    dur_a = _get_duration(a_path)
    dur_b = _get_duration(b_path)

    # Clamp crossfade so offset stays positive
    xf = min(crossfade_dur, dur_a - 0.1, dur_b - 0.1)
    if xf < 0.04:
        _concat_pair(a_path, b_path, out_path)
        return

    offset = dur_a - xf
    # Video: xfade with fps/timebase normalization.
    # Audio: acrossfade to match the video overlap timing and keep sync.
    filter_str = (
        f"[0:v]fps={TARGET_FPS},settb=AVTB[v0];"
        f"[1:v]fps={TARGET_FPS},settb=AVTB[v1];"
        f"[v0][v1]xfade=transition=fade:duration={xf}:offset={offset:.3f},"
        f"fps={TARGET_FPS},settb=AVTB[v];"
        f"[0:a][1:a]acrossfade=d={xf}[a]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        a_path,
        "-i",
        b_path,
        "-filter_complex",
        filter_str,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"xfade pair failed: {stderr_tail}")
        raise RuntimeError(f"xfade pair failed: {stderr_tail}")


def _concat_pair(a_path: str, b_path: str, out_path: str) -> None:
    """Hard-cut concatenation using the filter_complex concat filter.

    Uses the concat *filter* (not the concat demuxer) to properly reset
    timestamps and avoid gaps between segments.
    """
    filter_str = (
        f"[0:v]fps={TARGET_FPS},settb=AVTB[v0];"
        f"[1:v]fps={TARGET_FPS},settb=AVTB[v1];"
        f"[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[v][a]"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        a_path,
        "-i",
        b_path,
        "-filter_complex",
        filter_str,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error(f"concat pair failed: {stderr_tail}")
        raise RuntimeError(f"Concat pair failed: {stderr_tail}")


def create_title_card_video(
    image_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
    duration: float = 2.5,
    fps: int = TARGET_FPS,
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
        f"anullsrc=r={TARGET_AUDIO_RATE}:cl=stereo",
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
    delay: float = 0.5,
    fade_in: float = 0.3,
    hold: float = 1.5,
    fade_out: float = 0.3,
) -> str:
    """Overlay a PNG image on a video segment with fade in/out.

    The overlay starts after `delay` seconds so it appears after the
    crossfade transition is complete, not during it.
    """
    end = delay + fade_in + hold + fade_out

    # Get segment duration and resolution
    seg_dur = _get_duration(segment_path)
    probe_cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_streams",
        segment_path,
    ]
    probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)
    vid_w = 854  # fallback
    if probe_result.returncode == 0:
        streams = json.loads(probe_result.stdout).get("streams", [])
        vs = next((s for s in streams if s["codec_type"] == "video"), None)
        if vs:
            vid_w = int(vs["width"])

    # Scale overlay to 70% of video width (keep aspect ratio),
    # cap opacity at 85%, fade in/out after crossfade transition.
    ovr_w = int(vid_w * 0.7) // 2 * 2  # ensure even
    filter_graph = (
        f"[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[base];"
        f"[1:v]scale={ovr_w}:-1,format=rgba,"
        f"colorchannelmixer=aa=0.85,"
        f"fade=in:st={delay}:d={fade_in}:alpha=1,"
        f"fade=out:st={delay + fade_in + hold}:d={fade_out}:alpha=1[ovr];"
        f"[base][ovr]overlay=(W-w)/2:(H-h)/2"
        f":enable='between(t,{delay},{end})'"
        f",format=yuv420p"
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
            "-loop",
            "1",
            "-t",
            f"{seg_dur:.3f}",
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
        _safe_unlink(filter_path)


def _get_duration(path: str) -> float:
    """Get video duration in seconds via ffprobe.

    Tries format duration first, falls back to the longest stream duration.
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}")

    data = json.loads(result.stdout)
    dur = float(data.get("format", {}).get("duration", 0))
    if dur <= 0:
        # Fall back to longest stream duration
        for s in data.get("streams", []):
            s_dur = float(s.get("duration", 0))
            if s_dur > dur:
                dur = s_dur
    return dur


def _tmp_file(suffix: str) -> str:
    """Create a named temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ffmpeg_")
    os.close(fd)
    return path


def _safe_unlink(path: str) -> None:
    """Delete a file, ignoring errors."""
    try:
        os.unlink(path)
    except OSError:
        pass

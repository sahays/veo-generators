"""Promo generation — video segment extraction, normalization, and stitching.

No FastAPI or Firestore dependencies — easily testable.
"""

import logging
import os
import shutil
import tempfile
from typing import List

from ffmpeg_runner import (
    ffprobe_duration,
    ffprobe_has_audio,
    ffprobe_video_width,
    run_ffmpeg,
    run_ffmpeg_with_filter,
)

logger = logging.getLogger(__name__)

TARGET_FPS = 30
TARGET_AUDIO_RATE = 44100


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def parse_timestamp(ts: str) -> float:
    """Convert MM:SS or HH:MM:SS to seconds."""
    parts = [float(p) for p in ts.strip().split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


# ---------------------------------------------------------------------------
# Segment extraction
# ---------------------------------------------------------------------------


def extract_segment(
    src_path: str,
    out_path: str,
    start_sec: float,
    end_sec: float,
) -> str:
    """Extract a time-range segment from a video."""
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
    run_ffmpeg(
        cmd, timeout=300, label=f"extract-segment({start_sec:.1f}-{end_sec:.1f})"
    )

    dur = ffprobe_duration(out_path)
    if dur <= 0:
        raise RuntimeError(f"Extracted segment is empty: {start_sec}-{end_sec}s")
    return out_path


def extract_frame(src_path: str, out_path: str, timestamp_sec: float) -> str:
    """Extract a single frame as PNG at the given timestamp."""
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
    run_ffmpeg(cmd, timeout=60, label=f"extract-frame({timestamp_sec:.1f}s)")
    return out_path


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_segment(
    in_path: str,
    out_path: str,
    target_w: int,
    target_h: int,
    target_fps: int = TARGET_FPS,
) -> str:
    """Re-encode a segment to canonical format for reliable crossfade."""
    has_audio = ffprobe_has_audio(in_path)
    cmd = _build_normalize_cmd(
        in_path,
        out_path,
        target_w,
        target_h,
        target_fps,
        has_audio,
    )
    run_ffmpeg(cmd, timeout=300, label="normalize-segment")
    _validate_has_video_stream(out_path)
    return out_path


def _build_normalize_cmd(
    in_path,
    out_path,
    target_w,
    target_h,
    target_fps,
    has_audio,
) -> list:
    """Build FFmpeg command for segment normalization."""
    vf = (
        f"fps={target_fps},"
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,format=yuv420p"
    )
    cmd = ["ffmpeg", "-y", "-i", in_path]
    if not has_audio:
        seg_dur = ffprobe_duration(in_path) or 30.0
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
    cmd += (
        ["-c:a", "copy"]
        if has_audio
        else [
            "-c:a",
            "aac",
            "-ar",
            str(TARGET_AUDIO_RATE),
            "-ac",
            "2",
        ]
    )
    cmd += ["-movflags", "+faststart", out_path]
    return cmd


def _validate_has_video_stream(path: str) -> None:
    """Raise if output has no video stream."""
    from ffmpeg_runner import ffprobe_json

    data = ffprobe_json(path, timeout=30)
    has_video = any(s.get("codec_type") == "video" for s in data.get("streams", []))
    if not has_video:
        raise RuntimeError(f"Output has no video stream: {path}")


# ---------------------------------------------------------------------------
# Crossfade stitching
# ---------------------------------------------------------------------------


def concatenate_with_crossfade(
    segment_paths: List[str],
    out_path: str,
    crossfade_duration: float = 0.5,
) -> str:
    """Concatenate pre-normalized segments with cross-dissolve transitions."""
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

        try:
            _xfade_pair(current, segment_paths[i], pair_out, crossfade_duration)
        except RuntimeError:
            logger.warning(f"xfade failed for pair {i}, falling back to concat")
            _safe_unlink(pair_out)
            _concat_pair(current, segment_paths[i], pair_out)

        if current in intermediates:
            _safe_unlink(current)
            intermediates.remove(current)
        current = pair_out

    for f in intermediates:
        _safe_unlink(f)
    return out_path


def _xfade_pair(a_path: str, b_path: str, out_path: str, xf_dur: float) -> None:
    """Apply xfade + acrossfade between two pre-normalized segments."""
    dur_a = ffprobe_duration(a_path)
    dur_b = ffprobe_duration(b_path)
    xf = min(xf_dur, dur_a - 0.1, dur_b - 0.1)
    if xf < 0.04:
        _concat_pair(a_path, b_path, out_path)
        return

    offset = dur_a - xf
    filt = (
        f"[0:v]fps={TARGET_FPS},settb=AVTB[v0];"
        f"[1:v]fps={TARGET_FPS},settb=AVTB[v1];"
        f"[v0][v1]xfade=transition=fade:duration={xf}:offset={offset:.3f},"
        f"fps={TARGET_FPS},settb=AVTB[v];"
        f"[0:a][1:a]acrossfade=d={xf}[a]"
    )
    cmd = _build_pair_cmd(a_path, b_path, out_path, filt)
    run_ffmpeg(cmd, timeout=120, label="xfade-pair")


def _concat_pair(a_path: str, b_path: str, out_path: str) -> None:
    """Hard-cut concat using the concat filter."""
    filt = (
        f"[0:v]fps={TARGET_FPS},settb=AVTB[v0];"
        f"[1:v]fps={TARGET_FPS},settb=AVTB[v1];"
        f"[v0][0:a][v1][1:a]concat=n=2:v=1:a=1[v][a]"
    )
    cmd = _build_pair_cmd(a_path, b_path, out_path, filt)
    run_ffmpeg(cmd, timeout=120, label="concat-pair")


def _build_pair_cmd(a_path, b_path, out_path, filter_str) -> list:
    """Build FFmpeg command for a 2-input filter_complex operation."""
    return [
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


# ---------------------------------------------------------------------------
# Title card & overlay
# ---------------------------------------------------------------------------


def create_title_card_video(
    image_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
    duration: float = 2.5,
    fps: int = TARGET_FPS,
) -> str:
    """Convert a still image into a video clip with silent audio."""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
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
        vf,
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
    run_ffmpeg(cmd, timeout=60, label="title-card")
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
    """Overlay a PNG image on a video segment with fade in/out."""
    seg_dur = ffprobe_duration(segment_path)
    vid_w = ffprobe_video_width(segment_path)
    end = delay + fade_in + hold + fade_out
    filter_str = _build_overlay_filter(vid_w, delay, fade_in, hold, fade_out, end)

    from ffmpeg_runner import _FILTER_PLACEHOLDER

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
        _FILTER_PLACEHOLDER,
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
    run_ffmpeg_with_filter(
        cmd, filter_str, filter_flag="-/filter_complex", timeout=120, label="overlay"
    )
    return out_path


def _build_overlay_filter(
    vid_w: int,
    delay: float,
    fade_in: float,
    hold: float,
    fade_out: float,
    end: float,
) -> str:
    """Build filter_complex string for image overlay with fade."""
    ovr_w = int(vid_w * 0.7) // 2 * 2
    return (
        f"[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2[base];"
        f"[1:v]scale={ovr_w}:-1,format=rgba,"
        f"colorchannelmixer=aa=0.85,"
        f"fade=in:st={delay}:d={fade_in}:alpha=1,"
        f"fade=out:st={delay + fade_in + hold}:d={fade_out}:alpha=1[ovr];"
        f"[base][ovr]overlay=(W-w)/2:(H-h)/2"
        f":enable='between(t,{delay},{end})'"
        f",format=yuv420p"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_file(suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="ffmpeg_")
    os.close(fd)
    return path


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass

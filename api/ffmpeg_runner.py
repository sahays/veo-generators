"""Centralized FFmpeg/ffprobe execution.

Single source of truth for subprocess calls, temp filter file management,
and error handling. Eliminates duplicated patterns across service modules.
"""

import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def run_ffmpeg(cmd: list, timeout: int = 1200, label: str = "FFmpeg") -> str:
    """Run an FFmpeg command, raising RuntimeError on failure."""
    logger.info(f"{label}: {' '.join(cmd[:10])}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        stderr_tail = result.stderr[-1000:] if result.stderr else "(no stderr)"
        logger.error(f"{label} returncode={result.returncode}")
        logger.error(f"{label} stderr: {stderr_tail}")
        raise RuntimeError(f"{label} failed (exit {result.returncode}): {stderr_tail}")
    return result.stdout


_FILTER_PLACEHOLDER = "__FILTER_PATH__"


def run_ffmpeg_with_filter(
    cmd: list,
    filter_str: str,
    filter_flag: str = "-/filter:v",
    timeout: int = 1200,
    label: str = "FFmpeg",
) -> str:
    """Write filter to temp file, splice into cmd, run, clean up.

    Place the constant FILTER_PLACEHOLDER in cmd where the filter flag
    should go. If absent, the filter args are inserted right after the
    last -i input arg.
    """
    fd, filter_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_filter_")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(filter_str)
        full_cmd = _splice_filter(cmd, filter_flag, filter_path)
        return run_ffmpeg(full_cmd, timeout=timeout, label=label)
    finally:
        try:
            os.unlink(filter_path)
        except OSError:
            pass


def _splice_filter(cmd: list, flag: str, path: str) -> list:
    """Insert filter flag+path into cmd at the right position."""
    # If placeholder present, replace it
    if _FILTER_PLACEHOLDER in cmd:
        idx = cmd.index(_FILTER_PLACEHOLDER)
        return cmd[:idx] + [flag, path] + cmd[idx + 1 :]
    # Otherwise insert after the last -i arg
    last_i = max(i for i, a in enumerate(cmd) if a == "-i")
    insert_at = last_i + 2  # after -i and its value
    return cmd[:insert_at] + [flag, path] + cmd[insert_at:]


def ffprobe_json(path: str, timeout: int = 120) -> dict:
    """Run ffprobe and return parsed JSON output."""
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
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed on {path}: {result.stderr[-200:] if result.stderr else ''}"
        )
    return json.loads(result.stdout)


def ffprobe_video(path: str) -> dict:
    """Extract width, height, fps, duration, and has_audio from a video."""
    data = ffprobe_json(path)
    video_stream = next(
        (s for s in data.get("streams", []) if s["codec_type"] == "video"),
        None,
    )
    if not video_stream:
        raise RuntimeError("No video stream found in source file")

    fps_parts = video_stream.get("r_frame_rate", "30/1").split("/")
    fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0
    duration = float(data.get("format", {}).get("duration", 0))
    if duration == 0:
        duration = float(video_stream.get("duration", 0))

    return {
        "width": int(video_stream["width"]),
        "height": int(video_stream["height"]),
        "fps": fps,
        "duration": duration,
        "has_audio": any(s["codec_type"] == "audio" for s in data.get("streams", [])),
    }


def ffprobe_duration(path: str, timeout: int = 30) -> float:
    """Get media duration in seconds. Tries format, then longest stream."""
    data = ffprobe_json(path, timeout=timeout)
    dur = float(data.get("format", {}).get("duration", 0))
    if dur <= 0:
        for s in data.get("streams", []):
            s_dur = float(s.get("duration", 0))
            dur = max(dur, s_dur)
    return dur


def ffprobe_has_audio(path: str) -> bool:
    """Check whether a media file contains an audio stream."""
    data = ffprobe_json(path, timeout=30)
    return any(s["codec_type"] == "audio" for s in data.get("streams", []))


def ffprobe_video_width(path: str) -> int:
    """Get video width in pixels. Returns 854 as fallback."""
    try:
        data = ffprobe_json(path, timeout=30)
        vs = next(
            (s for s in data.get("streams", []) if s["codec_type"] == "video"),
            None,
        )
        return int(vs["width"]) if vs else 854
    except Exception:
        return 854

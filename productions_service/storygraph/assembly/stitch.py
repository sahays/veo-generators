"""Clip stitching back-ends for final assembly.

`ffmpeg_stitch` is the production path and raises `StoryGraphError` on any failure;
there is no silent fallback. `mock_concat_stitch` exists only for the mock video
provider on hosts without ffmpeg, where clips are themselves synthetic placeholders.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from ..errors import StoryGraphError

logger = logging.getLogger(__name__)

ClipStitcher = Callable[[list[bytes]], bytes]

_FFMPEG_TIMEOUT_S = 120
_MIN_VALID_MP4_BYTES = 256
_STDERR_TAIL_CHARS = 2000
_CONCAT_PREFIX = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i"]
_COPY_ARGS = ["-c", "copy", "-movflags", "+faststart"]
_REENCODE_ARGS = [
    "-c:v",
    "libx264",
    "-preset",
    "ultrafast",
    "-pix_fmt",
    "yuv420p",
    "-movflags",
    "+faststart",
]


def _log_ctx(what: str, why: str, **fields: object) -> dict[str, object]:
    return {
        "who": "storygraph.assembly",
        "where": "assembly.stitch",
        "what": what,
        "why": why,
        "how": "ffmpeg concat demuxer",
        **fields,
    }


def _run_concat(concat_txt: Path, out_file: Path, codec_args: list[str]) -> str:
    """Run one ffmpeg concat pass; return '' on success or the stderr tail on failure."""
    cmd = [*_CONCAT_PREFIX, str(concat_txt), *codec_args, str(out_file)]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=_FFMPEG_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{type(exc).__name__}: {exc}"
    ok = out_file.is_file() and out_file.stat().st_size > _MIN_VALID_MP4_BYTES
    if proc.returncode == 0 and ok:
        return ""
    tail = proc.stderr.decode("utf-8", errors="replace")[-_STDERR_TAIL_CHARS:]
    return tail or f"ffmpeg exited {proc.returncode} with empty output"


def _concat_in_tmpdir(clips: list[bytes], tmp_path: Path) -> bytes:
    lines: list[str] = []
    for idx, clip in enumerate(clips):
        clip_path = tmp_path / f"clip_{idx:03d}.mp4"
        clip_path.write_bytes(clip)
        lines.append(f"file '{clip_path}'")
    concat_txt = tmp_path / "concat.txt"
    concat_txt.write_text("\n".join(lines), encoding="utf-8")
    out_file = tmp_path / "final.mp4"
    copy_err = _run_concat(concat_txt, out_file, _COPY_ARGS)
    if not copy_err:
        return out_file.read_bytes()
    reencode_err = _run_concat(concat_txt, out_file, _REENCODE_ARGS)
    if not reencode_err:
        return out_file.read_bytes()
    logger.error(
        "ffmpeg failed to stitch clips (stream copy and re-encode)",
        extra=_log_ctx(
            "stitch_failed",
            "ffmpeg returned an error for both concat strategies",
            clip_count=len(clips),
            copy_stderr_tail=copy_err,
            reencode_stderr_tail=reencode_err,
        ),
    )
    raise StoryGraphError(f"ffmpeg failed to stitch {len(clips)} clips: {reencode_err}")


def ffmpeg_stitch(clips: list[bytes]) -> bytes:
    """Concatenate MP4 clips with ffmpeg; a single clip is returned unchanged."""
    if not clips:
        raise StoryGraphError("No clips to stitch")
    if len(clips) == 1:
        return clips[0]
    if shutil.which("ffmpeg") is None:
        logger.error(
            "ffmpeg binary not found; cannot stitch clips",
            extra=_log_ctx(
                "stitch_unavailable", "ffmpeg missing on PATH", clip_count=len(clips)
            ),
        )
        raise StoryGraphError("ffmpeg is not installed; cannot stitch final video")
    with tempfile.TemporaryDirectory() as tmpdir:
        return _concat_in_tmpdir(clips, Path(tmpdir))


def mock_concat_stitch(clips: list[bytes]) -> bytes:
    """Byte-concatenate synthetic mock clips (mock provider without ffmpeg only)."""
    if not clips:
        raise StoryGraphError("No clips to stitch")
    return b"".join(clips)


def select_stitcher(video_provider: str) -> ClipStitcher:
    """Return the stitcher for `video_provider`; real providers always use ffmpeg."""
    if video_provider == "mock" and shutil.which("ffmpeg") is None:
        return mock_concat_stitch
    return ffmpeg_stitch

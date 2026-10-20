"""Late hard-cut trimming: drop the tail of a single-take clip after a late scene cut.

Omni often inserts a hard cut near the end of a clip. When the first ffmpeg-detected cut lies
at or after `LATE_CUT_FRACTION` of the clip duration, the clip is re-encoded up to the cut
(video and audio cut by the same `-t`, so A/V stay in sync) and the trimmed clip is what gets
stored and QA'd. Earlier cuts are left for the critic (MEDIUM defect).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..qa.critic.severity import LATE_CUT_FRACTION
from .media_frames import detect_scene_cuts, probe_duration

_MIN_CLIP_BYTES = 1024
_MIN_HEAD_S = 0.25
_FRAME_GUARD_S = 0.02


@dataclass(frozen=True)
class TrimResult:
    """Outcome of a late-cut trim (`trimmed=False` leaves `clip_bytes` untouched)."""

    clip_bytes: bytes
    trimmed: bool = False
    original_duration_s: float = 0.0
    duration_s: float = 0.0
    cut_at_s: float = 0.0


def late_cut_time(
    cuts: tuple[float, ...], duration_s: float, fraction: float = LATE_CUT_FRACTION
) -> float | None:
    """The trim point: the first cut, if it lies in the late window; else None.

    Only the FIRST cut matters: if an earlier cut exists, trimming the tail cannot make the
    clip a single take, so the clip is left for the critic.
    """
    real = sorted(t for t in cuts if t > _MIN_HEAD_S)
    if not real or duration_s <= 0.0:
        return None
    first = real[0]
    return first if first >= fraction * duration_s else None


def _encode_head(in_mp4: Path, out_mp4: Path, seconds: float) -> bool:
    """Re-encode the first `seconds` of `in_mp4` (video+audio) into `out_mp4`."""
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-i",
        str(in_mp4),
        "-t",
        f"{seconds:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(out_mp4),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=60, check=False
    )
    return proc.returncode == 0 and out_mp4.is_file() and out_mp4.stat().st_size > 512


def _trim_file(tmp: Path, clip_bytes: bytes) -> TrimResult:
    in_mp4, out_mp4 = tmp / "in.mp4", tmp / "out.mp4"
    in_mp4.write_bytes(clip_bytes)
    duration = probe_duration(in_mp4)
    cut = late_cut_time(detect_scene_cuts(in_mp4), duration)
    if cut is None or not _encode_head(in_mp4, out_mp4, cut - _FRAME_GUARD_S):
        return TrimResult(clip_bytes, original_duration_s=duration, duration_s=duration)
    return TrimResult(
        clip_bytes=out_mp4.read_bytes(),
        trimmed=True,
        original_duration_s=duration,
        duration_s=round(probe_duration(out_mp4), 3),
        cut_at_s=cut,
    )


def trim_late_hard_cut(clip_bytes: bytes) -> TrimResult:
    """Trim a clip at a late hard cut (>= 75% of duration); no-op without ffmpeg/cut."""
    usable = shutil.which("ffmpeg") and shutil.which("ffprobe")
    if not usable or len(clip_bytes) <= _MIN_CLIP_BYTES:
        return TrimResult(clip_bytes)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            return _trim_file(Path(tmpdir), clip_bytes)
    except (OSError, subprocess.SubprocessError):
        return TrimResult(clip_bytes)

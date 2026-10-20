"""Audio loudness measurement (ffmpeg `volumedetect`) for rendered clips."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_MEAN_RE = re.compile(r"mean_volume:\s*(-?[0-9.]+|-inf) dB")
_MAX_RE = re.compile(r"max_volume:\s*(-?[0-9.]+|-inf) dB")
_SILENT_DB = -91.0


@dataclass(frozen=True)
class AudioLevels:
    """Mean / peak level in dBFS (`-91.0` stands in for digital silence)."""

    mean_db: float
    max_db: float


def _db(match: re.Match[str] | None) -> float:
    if match is None or match.group(1) == "-inf":
        return _SILENT_DB
    return float(match.group(1))


def measure_audio_levels(clip_bytes: bytes) -> AudioLevels | None:
    """Mean/peak dBFS of the clip's audio; None without ffmpeg or an audio stream."""
    if not shutil.which("ffmpeg") or len(clip_bytes) <= 256:
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        clip = Path(tmpdir) / "clip.mp4"
        clip.write_bytes(clip_bytes)
        cmd = ["ffmpeg", "-hide_banner", "-i", str(clip), "-vn", "-af", "volumedetect"]
        try:
            proc = subprocess.run(
                [*cmd, "-f", "null", "-"],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
    text = proc.stderr.decode(errors="ignore")
    mean = _MEAN_RE.search(text)
    if mean is None:
        return None
    return AudioLevels(mean_db=_db(mean), max_db=_db(_MAX_RE.search(text)))

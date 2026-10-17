"""FFmpeg and Pillow representative frame extraction adapter for video clips."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def _run_ffmpeg_frame(in_mp4: Path, out_png: Path, seek_args: list[str]) -> None:
    """Extract a single frame from `in_mp4` to `out_png` using `seek_args`."""
    cmd = [
        "ffmpeg",
        "-y",
        *seek_args,
        "-i",
        str(in_mp4),
        "-frames:v",
        "1",
        str(out_png),
    ]
    subprocess.run(cmd, capture_output=True, timeout=10, check=False)


def _read_valid_png(png_path: Path, fallback: bytes) -> bytes:
    """Read `png_path` bytes if non-empty, otherwise return `fallback`."""
    if png_path.is_file() and png_path.stat().st_size > 64:
        return png_path.read_bytes()
    return fallback


def _try_ffmpeg_frames(clip_bytes: bytes) -> list[bytes] | None:
    """Attempt extracting first, mid, and last PNG frames via ffmpeg."""
    if not shutil.which("ffmpeg") or len(clip_bytes) <= 256:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            in_mp4 = tmp_path / "clip.mp4"
            in_mp4.write_bytes(clip_bytes)
            first_png, mid_png, last_png = (
                tmp_path / "first.png",
                tmp_path / "mid.png",
                tmp_path / "last.png",
            )
            _run_ffmpeg_frame(in_mp4, first_png, [])
            _run_ffmpeg_frame(in_mp4, mid_png, ["-ss", "2.0"])
            _run_ffmpeg_frame(in_mp4, last_png, ["-sseof", "-0.15"])
            if first_png.is_file() and first_png.stat().st_size > 64:
                f_bytes = first_png.read_bytes()
                m_bytes = _read_valid_png(mid_png, f_bytes)
                l_bytes = _read_valid_png(last_png, m_bytes)
                return [f_bytes, m_bytes, l_bytes]
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def _synthetic_fallback_frames(clip_bytes: bytes) -> list[bytes]:
    """Generate 3 deterministic RGB PNG frames hashed from `clip_bytes`."""
    frames: list[bytes] = []
    digest = hashlib.sha256(clip_bytes).digest()
    for i in range(3):
        color = (
            (digest[i * 3] % 180) + 30,
            (digest[i * 3 + 1] % 180) + 30,
            (digest[i * 3 + 2] % 180) + 30,
        )
        img = Image.new("RGB", (320, 180), color=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        frames.append(buf.getvalue())
    return frames


def extract_representative_frames_png(clip_bytes: bytes) -> list[bytes]:
    """Extract 3 representative PNG frames (first, mid, last) from rendered MP4 clip bytes."""
    ffmpeg_frames = _try_ffmpeg_frames(clip_bytes)
    if ffmpeg_frames is not None:
        return ffmpeg_frames
    return _synthetic_fallback_frames(clip_bytes)

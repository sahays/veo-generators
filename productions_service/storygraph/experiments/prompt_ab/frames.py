"""Deterministic ffmpeg frame checks: 3 fps frame dump, hard-cut detection, contact sheet.

Independent of the VLM eval: cut times come from ffmpeg's scene-change score so a second,
model-free signal backs the "single continuous take" dimension.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .contracts import FrameCheck

FPS = 3
CUT_SCENE_THRESHOLD = 0.35
_PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def duration_s(clip: Path) -> float:
    out = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(clip),
        ]
    ).stdout.strip()
    return float(out) if out else 0.0


def cut_times(clip: Path, threshold: float = CUT_SCENE_THRESHOLD) -> tuple[float, ...]:
    """Timestamps where ffmpeg's scene score exceeds `threshold` (hard cuts)."""
    proc = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(clip),
            "-an",
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ]
    )
    return tuple(round(float(m.group(1)), 2) for m in _PTS_RE.finditer(proc.stderr))


def dump_frames(clip: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"fps={FPS}",
            str(out_dir / "f_%03d.jpg"),
        ]
    )
    return len(list(out_dir.glob("f_*.jpg")))


def contact_sheet(clip: Path, out_png: Path, cols: int = 6) -> str:
    """One 6-wide tile of frames at 1 fps (t=0.5s, 1.5s, ...) for the report."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"fps=1,scale=320:-1,tile={cols}x2",
            "-frames:v",
            "1",
            str(out_png),
        ]
    )
    return str(out_png) if out_png.exists() else ""


def check_clip(clip: Path, work_dir: Path) -> FrameCheck:
    frames_dir = work_dir / "frames" / clip.stem
    n = dump_frames(clip, frames_dir)
    sheet = contact_sheet(clip, work_dir / "sheets" / f"{clip.stem}.jpg")
    return FrameCheck(
        frames_dir=str(frames_dir),
        frames=n,
        cut_times_s=cut_times(clip),
        contact_sheet=sheet,
        duration_s=duration_s(clip),
    )

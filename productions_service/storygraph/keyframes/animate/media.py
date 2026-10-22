"""ffmpeg I/O for keyframe animation: build the 1 fps animatic and stitch interp segments.

Commands are argument lists (never a shell); all files live in a private temp directory.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .timing import animatic_schedule, concat_manifest

_TIMEOUT_S = 120
_ENCODE = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24"]
_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True, timeout=_TIMEOUT_S)


def build_animatic(frames: Sequence[bytes], duration_s: float) -> bytes:
    """MP4 (24 fps, no audio) holding each keyframe for its `animatic_schedule` slot."""
    with tempfile.TemporaryDirectory(prefix="animatic_") as tmp:
        root = Path(tmp)
        paths: list[str] = []
        for idx, png in enumerate(frames):
            path = root / f"k{idx:03d}.png"
            path.write_bytes(png)
            paths.append(str(path))
        manifest = root / "list.txt"
        manifest.write_text(
            concat_manifest(paths, animatic_schedule(len(frames), duration_s)),
            encoding="utf-8",
        )
        out = root / "animatic.mp4"
        pad = f"{_EVEN},fps=24,tpad=stop_mode=clone:stop_duration={duration_s:.3f}"
        _run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0"]
            + ["-i", str(manifest), "-vf", pad, *_ENCODE]
            + ["-t", f"{duration_s:.3f}", str(out)]
        )
        return out.read_bytes()


def _has_audio(path: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries"]
        + ["stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    return bool(probe.stdout.strip())


def _concat_filter(durations: Sequence[float], audio: bool) -> str:
    parts: list[str] = []
    for i, dur in enumerate(durations):
        parts.append(
            f"[{i}:v]trim=0:{dur:.3f},setpts=PTS-STARTPTS,{_EVEN},fps=24[v{i}]"
        )
        if audio:
            parts.append(f"[{i}:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[a{i}]")
    inputs = "".join(
        f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(len(durations))
    )
    a_flag = 1 if audio else 0
    parts.append(
        f"{inputs}concat=n={len(durations)}:v=1:a={a_flag}[v]"
        + ("[a]" if audio else "")
    )
    return ";".join(parts)


def stitch(segments: Sequence[bytes], durations: Sequence[float]) -> bytes:
    """Trim each segment to its planned duration and concatenate (audio kept if all have it)."""
    with tempfile.TemporaryDirectory(prefix="stitch_") as tmp:
        root = Path(tmp)
        paths = [root / f"s{i:02d}.mp4" for i in range(len(segments))]
        for path, data in zip(paths, segments, strict=True):
            path.write_bytes(data)
        audio = all(_has_audio(p) for p in paths)
        args = ["ffmpeg", "-y", "-loglevel", "error"]
        for path in paths:
            args += ["-i", str(path)]
        maps = ["-map", "[v]"] + (["-map", "[a]", "-c:a", "aac"] if audio else [])
        out = root / "stitched.mp4"
        _run(
            args
            + [
                "-filter_complex",
                _concat_filter(durations, audio),
                *maps,
                *_ENCODE,
                str(out),
            ]
        )
        return out.read_bytes()

"""Shared helpers for eval tests: synthetic ffmpeg clips and a minimal OmniClipSpec dict."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

SPEC: dict[str, Any] = {
    "task": "render_video_clip",
    "clip": {"duration_s": 4.0, "aspect": "16:9", "fps": 24, "audio": {}},
    "subjects": [
        {
            "id": "S1",
            "name": "Pip",
            "kind": "robot",
            "ref_image": "IMAGE_REF_0",
            "identity": "Matte teal casing, round blue eyes; tiny antenna",
            "screen_pos": "left",
            "framing": "MS",
            "can_speak": True,
            "has_mouth": True,
        }
    ],
    "setting": {"id": "L1", "name": "Kitchen"},
    "objects": [
        {
            "id": "O1",
            "name": "Bowl",
            "start": {"where": "on the counter"},
            "moves": False,
        }
    ],
    "camera": {"size": "MS", "angle": "eye", "move": "static", "lens_mm": 35},
    "sequence": [{"n": 1, "actor": "S1", "verb": "waves"}],
    "speech": [
        {
            "speaker": "S1",
            "lang": "hi",
            "text": "नमस्ते मिलो।",
            "voice": "v",
            "lipsync": True,
        },
        {
            "speaker": "S1",
            "lang": "hi",
            "text": "चलो खेलते हैं!",
            "voice": "v",
            "lipsync": True,
        },
    ],
    "constraints": ["single_continuous_take"],
}


def _run(cmd: list[str]) -> None:
    subprocess.run(
        cmd, capture_output=True, stdin=subprocess.DEVNULL, check=True, timeout=60
    )


def segments_clip(path: Path, segments: list[tuple[str, float]]) -> Path:
    """Concatenate solid-colour segments (each boundary is a hard cut) into one mp4."""
    cmd = ["ffmpeg", "-y", "-hide_banner"]
    for color, secs in segments:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=24:d={secs}"]
    inputs = "".join(f"[{i}:v]" for i in range(len(segments)))
    graph = f"{inputs}concat=n={len(segments)}:v=1:a=0[v]"
    _run(
        [
            *cmd,
            "-filter_complex",
            graph,
            "-map",
            "[v]",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return path


def moving_clip(path: Path, seconds: float) -> Path:
    """A smoothly moving test pattern (no freeze, no flicker, no cut)."""
    src = f"testsrc=s=160x90:r=24:d={seconds}"
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", str(path)])
    return path


def flicker_clip(path: Path, seconds: float) -> Path:
    """A moving pattern whose brightness alternates every 0.25 s (A-B-A flicker at 4 fps)."""
    src = f"testsrc=s=160x90:r=24:d={seconds}"
    vf = "eq=brightness='if(lt(mod(t,0.5),0.25),0,0.5)':eval=frame"
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            src,
            "-vf",
            vf,
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )
    return path

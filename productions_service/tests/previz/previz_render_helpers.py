"""Shared previz render test helpers: sample scenes, fake/real Blender, PNG I/O via ffmpeg."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

from storygraph.schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    CharacterKey,
    CharacterTrack,
    LocationLayout,
    PrevizScene,
    PropKey,
    PropTrack,
    RenderSettings,
    SetPiece,
    Vec3,
)

SCRATCH_BLENDER = Path(
    "/usr/local/google/home/sanjeetsahay/.gemini/jetski/brain/"
    "a1d4d15b-eb3e-484a-bf9e-6ade2df18c2c/scratch/blender/blender-4.2.23-linux-x64/blender"
)


def real_blender() -> str | None:
    """$BLENDER_BIN, the scratch build, or `blender` on PATH (None when unavailable)."""
    for candidate in (
        os.environ.get("BLENDER_BIN"),
        str(SCRATCH_BLENDER),
        shutil.which("blender"),
    ):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


HAVE_RENDER_TOOLS = real_blender() is not None and shutil.which("ffprobe") is not None


def sample_scene(
    duration: float = 1.0, width: int = 64, height: int = 36, fps: int = 12
) -> PrevizScene:
    """Tiny but complete scene: one set piece, a walking character, a prop she picks up."""
    keys = [
        CharacterKey(t=0.0, position=Vec3(x=-1.0, y=2.0), facing_deg=90.0, pose="walk"),
        CharacterKey(
            t=duration, position=Vec3(x=0.0, y=2.0), facing_deg=0.0, pose="reach"
        ),
    ]
    prop_keys = [
        PropKey(t=0.0, position=Vec3(x=0.5, y=2.5, z=0.8)),
        PropKey(t=duration / 2, position=Vec3(x=0.5, y=2.5, z=0.8), holder_id="ava"),
    ]
    table = SetPiece(
        entity_id="t",
        name="Table",
        kind="table",
        position=Vec3(x=0.5, y=2.5),
        size=Vec3(x=1, y=0.6, z=0.75),
    )
    return PrevizScene(
        layout=LocationLayout(location_id="loc", name="Room", set_pieces=[table]),
        camera=CameraRig(
            position=Vec3(y=-4.0, z=1.6),
            target=Vec3(y=2.0, z=1.0),
            end_position=Vec3(x=0.5, y=-3.5, z=1.6),
        ),
        blocking=BlockingTrack(
            shot_id="shot1",
            scene_id="scene1",
            clip_index=0,
            duration_s=duration,
            characters=[
                CharacterTrack(entity_id="ava", name="Ava", color="#3070d0", keys=keys)
            ],
            props=[
                PropTrack(entity_id="cup", name="Cup", color="#20c020", keys=prop_keys)
            ],
        ),
        render=RenderSettings(width=width, height=height, fps=fps),
    )


def fake_blender(tmp_path: Path, body: str) -> str:
    """Executable shell script standing in for Blender (argv mirrors the real command)."""
    script = tmp_path / "fake_blender.sh"
    header = '#!/bin/sh\nif [ "${1:-}" = "--version" ]; then echo "Blender 4.2.0"; exit 0; fi\n'
    script.write_text(header + body + "\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


def write_png_rgb(path: Path, width: int, height: int, rgb: bytes) -> None:
    """Minimal 8-bit RGB PNG writer (stdlib only)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    rows = b"".join(
        b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def decode(path: Path, pix_fmt: str, frame: int = 0) -> bytes:
    """Raw pixels of one image / video frame via ffmpeg (rgb24 or gray16le)."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{frame})",
           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", pix_fmt, "-"]  # fmt: skip
    return subprocess.run(cmd, capture_output=True, check=True).stdout

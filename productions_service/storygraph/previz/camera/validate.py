"""Validate a plate calibration by rendering the room box with Blender and comparing edges.

`render_still` renders a 1-second greybox clip of a layout through a camera rig at the plate's
aspect (480 px wide) and returns its first frame; `overlay_edges` draws the render's edges in
red over the plate; `retarget_pieces` moves set pieces placed through one master camera onto
the same plate positions under another (e.g. the calibrated one), so before/after renders
compare like with like.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path
from typing import Final

import numpy as np
from PIL import Image

from ...schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    LocationLayout,
    PrevizScene,
    RenderSettings,
    Room,
    SetPiece,
    Vec3,
)  # fmt: skip
from ..blocking.project import MasterCamera, to_image, world_x
from ..render.runner import BlenderRunner
from .edges import ANALYSIS_WIDTH, dilate, edge_map

FFMPEG_TIMEOUT_S: Final[float] = 30.0
EDGE_RGB: Final[tuple[int, int, int]] = (255, 0, 0)


def render_size(
    plate_w: int, plate_h: int, width: int = ANALYSIS_WIDTH
) -> tuple[int, int]:
    """(w, h) at `width` keeping the plate aspect, both even (H.264)."""
    h = round(width * plate_h / plate_w)
    return width - width % 2, max(2, h - h % 2)


def first_frame(mp4: Path) -> bytes | None:
    """PNG bytes of the clip's first frame (None if ffmpeg fails)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "f0.png"
        subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["ffmpeg", "-y", "-i", str(mp4), "-frames:v", "1", str(out)],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=FFMPEG_TIMEOUT_S,
            check=False,
        )  # fmt: skip
        return out.read_bytes() if out.is_file() and out.stat().st_size > 0 else None


def render_still(
    runner: BlenderRunner,
    layout: LocationLayout,
    rig: CameraRig,
    size: tuple[int, int],
    workdir: Path,
) -> bytes | None:
    """First frame of a 1 s greybox render of `layout` through `rig` (None on failure)."""
    scene = PrevizScene(
        layout=layout,
        camera=rig,
        blocking=BlockingTrack(
            shot_id="calibration", scene_id="calibration", clip_index=0, duration_s=1.0
        ),
        render=RenderSettings(width=size[0], height=size[1], fps=2),
    )
    result = runner.render(scene, workdir)
    return first_frame(result.mp4_path) if result.ok and result.mp4_path else None


def overlay_edges(plate_png: bytes, render_png: bytes, quality: int = 88) -> bytes:
    """JPEG: the plate at analysis width with the render's edges painted red."""
    plate = Image.open(io.BytesIO(plate_png)).convert("RGB")
    h = round(ANALYSIS_WIDTH * plate.height / plate.width)
    plate = plate.resize((ANALYSIS_WIDTH, h), Image.Resampling.BILINEAR)
    edges = dilate(edge_map(render_png, size=(ANALYSIS_WIDTH, h)), 1)
    pixels = np.asarray(plate).copy()
    pixels[edges] = EDGE_RGB
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _retarget(piece: SetPiece, old: MasterCamera, new: MasterCamera,
              old_room: Room, room: Room) -> SetPiece:  # fmt: skip
    """Same plate x and relative depth under `new` / `room`, kept inside the room."""
    mid = piece.size.z / 2
    plate_x = to_image(old, Vec3(x=piece.position.x, y=piece.position.y, z=mid))[0]
    frac = piece.position.y / max(old_room.depth, 1e-6)
    half_y = piece.size.y / 2
    y = min(max(frac * room.depth, half_y), room.depth - half_y)
    half_x = room.width / 2 - piece.size.x / 2
    x = min(max(world_x(new, plate_x, y, mid), -half_x), half_x)
    return piece.model_copy(
        update={"position": Vec3(x=round(x, 3), y=round(y, 3), z=0.0)}
    )


def retarget_pieces(
    layout: LocationLayout, old: MasterCamera, new: MasterCamera, room: Room
) -> LocationLayout:
    """`layout` in `room` with every set piece moved from `old`'s plate mapping to `new`'s."""
    pieces = [_retarget(p, old, new, layout.room, room) for p in layout.set_pieces]
    return layout.model_copy(update={"room": room, "set_pieces": pieces})

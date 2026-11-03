"""Pinhole camera + room-box geometry for plate calibration (pure numpy).

World frame as in `schemas.previz_scene`: +X right, +Y depth, +Z up, floor Z=0, room X in
[-W/2, W/2], Y in [0, D] (Y=0 is the open front of the box, Y=D the back wall). The camera
is a parameter vector (`NAMES`): position (cam_x, cam_y, cam_h), pitch (+ = up) and yaw
(+ = towards +X... kept 0 by default), `focal` = focal length in units of the image width
(f_px = focal * width, horizontal FOV = 2 atan(1 / (2 focal))), Blender lens shifts, and the
room box (width, depth, height). Projection uses homogeneous image points so lines through
points behind the camera stay correct.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from ...schemas.previz_scene import CameraRig, Room, Vec3
from ..blocking.project import Aspect, master_camera

Floats = NDArray[np.float64]
NAMES: Final[tuple[str, ...]] = (
    "cam_x", "cam_y", "cam_h", "pitch", "yaw", "focal", "shift_x", "shift_y",
    "width", "depth", "height",
)  # fmt: skip
IDX: Final[dict[str, int]] = {n: i for i, n in enumerate(NAMES)}
SENSOR_MM: Final[float] = 36.0
CORNER_UNITS: Final[dict[str, tuple[float, float, float]]] = {
    "back_bl": (-0.5, 1.0, 0.0),
    "back_br": (0.5, 1.0, 0.0),
    "back_tr": (0.5, 1.0, 1.0),
    "back_tl": (-0.5, 1.0, 1.0),
    "front_bl": (-0.5, 0.0, 0.0),
    "front_br": (0.5, 0.0, 0.0),
    "front_tr": (0.5, 0.0, 1.0),
    "front_tl": (-0.5, 0.0, 1.0),
}
EDGES: Final[dict[str, tuple[str, str]]] = {
    "back_bottom": ("back_bl", "back_br"),
    "back_top": ("back_tl", "back_tr"),
    "back_left": ("back_bl", "back_tl"),
    "back_right": ("back_br", "back_tr"),
    "floor_left": ("front_bl", "back_bl"),
    "floor_right": ("front_br", "back_br"),
    "top_left": ("front_tl", "back_tl"),
    "top_right": ("front_tr", "back_tr"),
    "front_left": ("front_bl", "front_tl"),
    "front_right": ("front_br", "front_tr"),
    "front_floor": ("front_bl", "front_br"),
}


@dataclass(frozen=True)
class Frame:
    """Pixel size of the image the camera renders."""

    width: int
    height: int


def params(**values: float) -> Floats:
    """Parameter vector from keyword values (unspecified entries 0)."""
    v = np.zeros(len(NAMES), dtype=float)
    for name, value in values.items():
        v[IDX[name]] = value
    return v


def basis(v: Floats) -> tuple[Floats, Floats, Floats]:
    """(right, up, forward) unit vectors of the camera (no roll)."""
    p, y = v[IDX["pitch"]], v[IDX["yaw"]]
    cp, sp, cy, sy = math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    right = np.array([cy, -sy, 0.0])
    fwd = np.array([sy * cp, cy * cp, sp])
    up = np.array([-sy * sp, -cy * sp, cp])
    return right, up, fwd


def _intrinsics(v: Floats, frame: Frame) -> tuple[float, float, float]:
    """(f_px, principal u, principal v); Blender shifts are fractions of the larger side."""
    big = max(frame.width, frame.height)
    return (
        v[IDX["focal"]] * frame.width,
        frame.width / 2 - v[IDX["shift_x"]] * big,
        frame.height / 2 + v[IDX["shift_y"]] * big,
    )


def homogeneous(v: Floats, dirs: Floats, frame: Frame) -> Floats:
    """(N,3) homogeneous image points of camera-relative world vectors `dirs` (N,3)."""
    right, up, fwd = basis(v)
    f, cu, cv = _intrinsics(v, frame)
    x, y, z = dirs @ right, dirs @ up, dirs @ fwd
    return np.stack([f * x + cu * z, -f * y + cv * z, z], axis=1)


def corner_points(v: Floats) -> dict[str, Floats]:
    """World coordinates of the 8 room-box corners."""
    dims = np.array([v[IDX["width"]], v[IDX["depth"]], v[IDX["height"]]])
    return {k: np.array(u) * dims for k, u in CORNER_UNITS.items()}


def camera_position(v: Floats) -> Floats:
    return np.array([v[IDX["cam_x"]], v[IDX["cam_y"]], v[IDX["cam_h"]]])


def corner_depths(v: Floats) -> dict[str, float]:
    """Signed distance of every box corner along the view axis (<= 0: behind the lens)."""
    _, _, fwd = basis(v)
    pos = camera_position(v)
    return {k: float((p - pos) @ fwd) for k, p in corner_points(v).items()}


def project(v: Floats, points: Floats, frame: Frame) -> Floats:
    """(N,2) pixel coordinates of world points (depth clamped just in front of the lens)."""
    h = homogeneous(v, points - camera_position(v), frame)
    return h[:, :2] / np.maximum(h[:, 2:3], 1e-6)


def project_corners(v: Floats, frame: Frame) -> dict[str, tuple[float, float]]:
    names = list(CORNER_UNITS)
    pts = project(v, np.stack([corner_points(v)[n] for n in names]), frame)
    return {n: (float(p[0]), float(p[1])) for n, p in zip(names, pts, strict=True)}


def edge_lines(v: Floats, frame: Frame) -> dict[str, Floats]:
    """Normalised homogeneous image line (a, b, c), a^2 + b^2 = 1, of every box edge."""
    corners = corner_points(v)
    names = list(CORNER_UNITS)
    hom = homogeneous(
        v, np.stack([corners[n] for n in names]) - camera_position(v), frame
    )
    by_name = dict(zip(names, hom, strict=True))
    out: dict[str, Floats] = {}
    for edge, (a, b) in EDGES.items():
        line = np.cross(by_name[a], by_name[b])
        out[edge] = line / (math.hypot(line[0], line[1]) or 1.0)
    return out


def depth_vp(v: Floats, frame: Frame) -> tuple[float, float]:
    """Image vanishing point of the +Y (depth) direction."""
    h = homogeneous(v, np.array([[0.0, 1.0, 0.0]]), frame)[0]
    return float(h[0] / h[2]), float(h[1] / h[2])


def hfov_deg(v: Floats) -> float:
    return math.degrees(2 * math.atan(1 / (2 * v[IDX["focal"]])))


def to_rig(v: Floats) -> CameraRig:
    """Blender camera: Track-To target on the view axis at the back-wall distance."""
    pos = camera_position(v)
    _, _, fwd = basis(v)
    reach = max(v[IDX["depth"]] - v[IDX["cam_y"]], 1.0) / max(fwd[1], 1e-3)
    tgt = pos + fwd * reach
    return CameraRig(
        position=Vec3(x=round(pos[0], 4), y=round(pos[1], 4), z=round(pos[2], 4)),
        target=Vec3(x=round(tgt[0], 4), y=round(tgt[1], 4), z=round(tgt[2], 4)),
        lens_mm=round(float(v[IDX["focal"]] * SENSOR_MM), 3),
        sensor_width_mm=SENSOR_MM,
        shift_x=round(float(v[IDX["shift_x"]]), 5),
        shift_y=round(float(v[IDX["shift_y"]]), 5),
    )


def to_room(v: Floats, base: Room | None = None) -> Room:
    """`base` (colours) with the calibrated box dimensions."""
    room = base or Room()
    return room.model_copy(
        update={
            "width": round(float(v[IDX["width"]]), 3),
            "depth": round(float(v[IDX["depth"]]), 3),
            "height": round(float(v[IDX["height"]]), 3),
        }
    )


def from_master(room: Room, aspect: Aspect = "16:9") -> Floats:
    """Parameter vector of the default (uncalibrated) master camera for `room`."""
    cam = master_camera(room, aspect)
    dy, dz = cam.target.y - cam.position.y, cam.target.z - cam.position.z
    return params(
        cam_x=cam.position.x,
        cam_y=cam.position.y,
        cam_h=cam.position.z,
        pitch=math.atan2(dz, dy),
        focal=1 / (2 * cam.tan_h),
        width=room.width,
        depth=room.depth,
        height=room.height,
    )

"""Plate-space <-> world projection through the master camera (pure geometry).

The master camera is the camera the scene plate was drawn from. Without calibration it is
synthetic: in front of the room at (0, -dist, EYE_H) looking along +Y at the room centre
(35 mm lens, 36 mm sensor on the frame's larger side, as Blender's AUTO fit does). A
calibrated `CameraRig` (any yaw/pitch, sensor fit HORIZONTAL, lens shift; roll ignored)
becomes the same `MasterCamera` via `camera_from_rig`, so every map below works for both:
`world_x` and `to_image` are exact inverses (O(1), a linear solve along X), `hit_plane`
intersects a pixel ray with an axis plane (floor, back wall, side wall). `XRemap` maps
another scene's plate x onto this layout's plate x through shared set pieces.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from ...schemas.previz_scene import CameraRig, Room, Vec3

Aspect = Literal["16:9", "9:16"]
Axis = Literal[0, 1, 2]  # X, Y, Z
LENS_MM: Final[float] = 35.0
SENSOR_MM: Final[float] = 36.0
EYE_H: Final[float] = 1.7
MIN_DIST: Final[float] = 2.5
TARGET_H: Final[float] = 0.9
Basis = tuple[tuple[float, float, float], ...]


@dataclass(frozen=True)
class MasterCamera:
    position: Vec3
    target: Vec3
    tan_h: float  # half-width of the frame at unit distance
    tan_v: float  # half-height of the frame at unit distance
    shift_x: float = 0.0  # principal-point offset in frame widths (Blender shift)
    shift_y: float = 0.0  # in frame heights

    @property
    def basis(self) -> Basis:
        """(right, up, forward) unit vectors; right stays horizontal (no roll)."""
        p, t = self.position, self.target
        f = (t.x - p.x, t.y - p.y, t.z - p.z)
        n = math.sqrt(sum(c * c for c in f)) or 1.0
        fx, fy, fz = f[0] / n, f[1] / n, f[2] / n
        h = math.hypot(fx, fy) or 1.0
        rx, ry = fy / h, -fx / h
        up = (ry * fz, -rx * fz, rx * fy - ry * fx)  # right x forward
        return (rx, ry, 0.0), up, (fx, fy, fz)


def _ratio(aspect: Aspect) -> float:
    """Frame height / width."""
    return 9 / 16 if aspect == "16:9" else 16 / 9


def half_tans(aspect: Aspect, lens_mm: float = LENS_MM) -> tuple[float, float]:
    """(tan_h, tan_v): the sensor spans the larger frame side (synthetic camera)."""
    big = SENSOR_MM / (2 * lens_mm)
    return (big, big * 9 / 16) if aspect == "16:9" else (big * 9 / 16, big)


def master_camera(
    room: Room, aspect: Aspect = "16:9", rig: CameraRig | None = None
) -> MasterCamera:
    """The calibrated rig when given, else back far enough that the back wall fills the
    frame width (never closer than MIN_DIST)."""
    if rig is not None:
        return camera_from_rig(rig, aspect)
    tan_h, tan_v = half_tans(aspect)
    dist = max(MIN_DIST, room.width / (2 * tan_h) - room.depth)
    return MasterCamera(
        position=Vec3(x=0.0, y=-round(dist, 4), z=EYE_H),
        target=Vec3(x=0.0, y=room.depth / 2, z=TARGET_H),
        tan_h=tan_h,
        tan_v=tan_v,
    )


def camera_from_rig(rig: CameraRig, aspect: Aspect = "16:9") -> MasterCamera:
    """Sensor fit HORIZONTAL; Blender shifts are fractions of the larger frame side."""
    tan_h = rig.sensor_width_mm / (2 * rig.lens_mm)
    ratio = _ratio(aspect)
    wide = ratio < 1
    return MasterCamera(
        position=rig.position,
        target=rig.target,
        tan_h=tan_h,
        tan_v=tan_h * ratio,
        shift_x=rig.shift_x if wide else rig.shift_x / ratio,
        shift_y=rig.shift_y / ratio if wide else rig.shift_y,
    )


def rig_from_camera(cam: MasterCamera, aspect: Aspect = "16:9") -> CameraRig:
    """Inverse of `camera_from_rig` at LENS_MM (the synthetic master as a render rig)."""
    ratio = _ratio(aspect)
    wide = ratio < 1
    return CameraRig(
        position=cam.position,
        target=cam.target,
        lens_mm=LENS_MM,
        sensor_width_mm=round(cam.tan_h * 2 * LENS_MM, 4),
        shift_x=cam.shift_x if wide else cam.shift_x * ratio,
        shift_y=cam.shift_y * ratio if wide else cam.shift_y,
    )


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cam_coords(cam: MasterCamera, p: Vec3) -> tuple[float, float, float]:
    """(right, up, forward) camera-space coordinates of world point `p`."""
    d = (p.x - cam.position.x, p.y - cam.position.y, p.z - cam.position.z)
    right, up, fwd = cam.basis
    return _dot(d, right), _dot(d, up), _dot(d, fwd)


def to_image(cam: MasterCamera, p: Vec3) -> tuple[float, float]:
    """Plate (x, y) of `p`: x 0 = left .. 1 = right, y 0 = top .. 1 = bottom."""
    right, up, fwd = _cam_coords(cam, p)
    fwd = max(fwd, 1e-6)
    x = 0.5 + right / (2 * fwd * cam.tan_h) - cam.shift_x
    return x, 0.5 - up / (2 * fwd * cam.tan_v) + cam.shift_y


def world_x(cam: MasterCamera, x_img: float, y: float, z: float) -> float:
    """World X of plate x at depth `y` / height `z` (exact inverse of `to_image` x)."""
    right, _, fwd = cam.basis
    k = (x_img - 0.5 + cam.shift_x) * 2 * cam.tan_h
    dy, dz = y - cam.position.y, z - cam.position.z
    rest = k * (fwd[1] * dy + fwd[2] * dz) - right[1] * dy
    denom = right[0] - k * fwd[0]
    return cam.position.x + rest / (denom if abs(denom) > 1e-9 else 1e-9)


def ray(cam: MasterCamera, x_img: float, y_img: float) -> tuple[float, float, float]:
    """World direction of the pixel ray through plate (x, y) (not normalised)."""
    right, up, fwd = cam.basis
    a = (x_img - 0.5 + cam.shift_x) * 2 * cam.tan_h
    b = (0.5 - y_img + cam.shift_y) * 2 * cam.tan_v
    return (
        fwd[0] + a * right[0] + b * up[0],
        fwd[1] + a * right[1] + b * up[1],
        fwd[2] + a * right[2] + b * up[2],
    )


def hit_plane(
    cam: MasterCamera, x_img: float, y_img: float, axis: Axis, value: float
) -> Vec3 | None:
    """Where the pixel ray meets the plane `coord[axis] == value` (None: behind/parallel)."""
    d = ray(cam, x_img, y_img)
    origin = (cam.position.x, cam.position.y, cam.position.z)
    if abs(d[axis]) < 1e-9:
        return None
    s = (value - origin[axis]) / d[axis]
    if s <= 0:
        return None
    return Vec3(x=origin[0] + s * d[0], y=origin[1] + s * d[1], z=origin[2] + s * d[2])


def floor_start(cam: MasterCamera, room: Room) -> float:
    """Nearest floor depth visible at the bottom of the plate (clamped into the room)."""
    hit = hit_plane(cam, 0.5, 1.0, 2, 0.0)
    return 0.0 if hit is None else min(max(hit.y, 0.0), room.depth * 0.6)


class XRemap:
    """Monotone piecewise-linear map scene-plate x -> layout-plate x via shared anchors."""

    def __init__(self, pairs: Mapping[str, tuple[float, float]]) -> None:
        points = sorted(pairs.values())
        xs, ys = [0.0], [0.0]
        for src, dst in points:
            if xs[-1] < src < 1.0 and ys[-1] < dst < 1.0:
                xs.append(src)
                ys.append(dst)
        self.xs, self.ys = xs + [1.0], ys + [1.0]

    def __call__(self, x: float) -> float:
        i = min(max(bisect_right(self.xs, x), 1), len(self.xs) - 1)
        x0, x1, y0, y1 = self.xs[i - 1], self.xs[i], self.ys[i - 1], self.ys[i]
        return y0 + (y1 - y0) * (x - x0) / (x1 - x0)

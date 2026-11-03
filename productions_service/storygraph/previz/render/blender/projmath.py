"""Pure pinhole maths matching a Blender camera (Track-To target, roll, HORIZONTAL fit, shift).

Basis: forward f = normalize(target - position); right r = normalize(f x +Z); up u = r x f;
roll rotates (r, u) counter-clockwise about the view axis. With sensor fit HORIZONTAL the
frame width at unit depth is W = sensor_width / lens and lens shifts are in units of W
(for both axes), so image coords are u = (X - shift_x W) / W + 0.5,
v = (Y - shift_y W) / (W / aspect) + 0.5 with X = x/depth, Y = y/depth. (0, 0) = bottom-left.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

Vec = tuple[float, float, float]


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Vec) -> Vec:
    n = math.sqrt(_dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


@dataclass(frozen=True)
class Pinhole:
    position: Vec
    right: Vec
    up: Vec
    forward: Vec
    width_at_unit: float  # sensor_width / lens
    shift_x: float
    shift_y: float
    aspect: float  # image width / height


def _num(rig: dict[str, Any], name: str, default: float) -> float:
    value = rig.get(name)
    return default if value is None else float(value)


def make_pinhole(rig: dict[str, Any], aspect: float) -> Pinhole:
    """Pinhole from a CameraRig JSON dict (start pose) and the image aspect."""
    pos = _vec(rig.get("position"), (0.0, -6.0, 1.6))
    tgt = _vec(rig.get("target"), (0.0, 3.0, 1.2))
    f = _norm(_sub(tgt, pos))
    r = _norm(_cross(f, (0.0, 0.0, 1.0)))
    u = _cross(r, f)
    roll = math.radians(_num(rig, "roll_deg", 0.0))
    c, s = math.cos(roll), math.sin(roll)
    r2 = (c * r[0] + s * u[0], c * r[1] + s * u[1], c * r[2] + s * u[2])
    u2 = (-s * r[0] + c * u[0], -s * r[1] + c * u[1], -s * r[2] + c * u[2])
    width = _num(rig, "sensor_width_mm", 36.0) / max(_num(rig, "lens_mm", 35.0), 1e-3)
    shift = (_num(rig, "shift_x", 0.0), _num(rig, "shift_y", 0.0))
    return Pinhole(pos, r2, u2, f, width, shift[0], shift[1], aspect)


def project(cam: Pinhole, point: Vec) -> tuple[float, float, float]:
    """World point -> (u, v, depth); depth <= 0 means behind the camera."""
    d = _sub(point, cam.position)
    depth = _dot(d, cam.forward)
    if depth <= 1e-9:
        return (-1.0, -1.0, depth)
    x, y = _dot(d, cam.right) / depth, _dot(d, cam.up) / depth
    w = cam.width_at_unit
    return (
        (x - cam.shift_x * w) / w + 0.5,
        (y - cam.shift_y * w) / (w / cam.aspect) + 0.5,
        depth,
    )


def _vec(data: Any, default: Vec) -> Vec:
    if not isinstance(data, dict):
        return default
    return (
        float(data.get("x", 0.0)),
        float(data.get("y", 0.0)),
        float(data.get("z", 0.0)),
    )

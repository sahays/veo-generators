"""Shot camera rig from the plan's camera spec (pure, deterministic).

WS = the master camera (the plate's camera: calibrated when the camera stage supplied one,
else synthetic, framing the whole room) with its lens, sensor and lens shift; EWS pulls it
back further. Tighter sizes stay in the master's family so clips of one scene cut cleanly:
the camera sits on the 3D line from the subject's look-at point towards the master camera
at a fixed distance per size, so it keeps the master's yaw AND pitch (it is simply nearer),
with the master's sensor width, no plate shift and the plan's lens. Angle raises/lowers
the camera; movement sets the end pose: dolly in/out along the view line, pan/tilt turns
the target, track/truck slides both, crane lifts. Move magnitudes scale with the clip
duration and are capped by the framing distance.
"""

from __future__ import annotations

import math
from typing import Final

from ...keyframes.plan.models import CameraInput
from ...schemas.previz_scene import CameraRig, LocationLayout, Vec3
from ..blocking.project import Aspect, master_camera, rig_from_camera

# shot size -> (distance to focus m, target height as a fraction of the subject height)
_SIZES: Final[dict[str, tuple[float, float]]] = {
    "MLS": (4.5, 0.55),
    "MS": (3.0, 0.7),
    "MCU": (1.8, 0.82),
    "CU": (1.1, 0.88),
    "ECU": (0.6, 0.9),
}
EWS_PULLBACK: Final[float] = 0.35
MOVE_SPEED: Final[float] = 0.35  # m/s for dolly / track
MOVE_CAP: Final[float] = 0.4  # fraction of the framing distance
TURN_DEG: Final[float] = 15.0
CRANE_M: Final[float] = 1.0
DEFAULT_SUBJECT: Final[float] = 1.6
MIN_CAM_Z: Final[float] = 0.3


def _v(x: float, y: float, z: float) -> Vec3:
    return Vec3(x=round(x, 3), y=round(y, 3), z=round(z, 3))


def master_rig(
    layout: LocationLayout, aspect: Aspect = "16:9", master: CameraRig | None = None
) -> CameraRig:
    """The calibrated master, else the synthetic master camera as a render rig."""
    return master or rig_from_camera(master_camera(layout.room, aspect), aspect)


def _wide(master: CameraRig, shot_size: str) -> tuple[Vec3, Vec3]:
    pos, tgt = master.position, master.target
    if shot_size == "EWS":
        k = 1 + EWS_PULLBACK
        pos = _v(tgt.x + (pos.x - tgt.x) * k, tgt.y + (pos.y - tgt.y) * k, pos.z)
    return pos, tgt


def _close(
    layout: LocationLayout, master: CameraRig, shot_size: str, focus: Vec3 | None
) -> tuple[Vec3, Vec3]:
    """On the 3D line look-at point -> master camera: same yaw and pitch, nearer."""
    dist, frac = _SIZES[shot_size]
    fx, fy = (focus.x, focus.y) if focus else (0.0, layout.room.depth / 2)
    height = focus.z if focus and focus.z > 0 else DEFAULT_SUBJECT
    tgt = _v(fx, fy, height * frac)
    m = master.position
    d = (m.x - tgt.x, m.y - tgt.y, m.z - tgt.z)
    norm = math.sqrt(sum(c * c for c in d)) or 1.0
    z = max(tgt.z + d[2] / norm * dist, MIN_CAM_Z)
    return _v(tgt.x + d[0] / norm * dist, tgt.y + d[1] / norm * dist, z), tgt


def _angled(pos: Vec3, tgt: Vec3, angle: str) -> Vec3:
    a = angle.lower()
    if "overhead" in a or "bird" in a:
        return _v(pos.x, pos.y, tgt.z + 3.0)
    if "high" in a:
        return _v(pos.x, pos.y, tgt.z + 1.2)
    if "low" in a:
        return _v(pos.x, pos.y, max(0.4, tgt.z - 0.8))
    return pos


def _basis(pos: Vec3, tgt: Vec3) -> tuple[float, float, float]:
    """(horizontal distance, right-axis x, right-axis y) of the camera."""
    dx, dy = tgt.x - pos.x, tgt.y - pos.y
    norm = math.hypot(dx, dy) or 1.0
    return norm, dy / norm, -dx / norm


def _moved(
    pos: Vec3, tgt: Vec3, movement: str, duration_s: float
) -> tuple[Vec3, Vec3] | None:
    m = movement.lower().replace("-", "_").replace(" ", "_")
    dist, rx, ry = _basis(pos, tgt)
    sign = -1.0 if m.endswith("_l") or "left" in m else 1.0
    amount = min(MOVE_CAP * dist, MOVE_SPEED * duration_s)
    turn = dist * math.tan(math.radians(TURN_DEG))
    if "dolly" in m or "push" in m or "pull" in m or "zoom" in m:
        k = (-1.0 if "out" in m or "pull" in m else 1.0) * amount / dist
        return _v(pos.x + (tgt.x - pos.x) * k, pos.y + (tgt.y - pos.y) * k, pos.z), tgt
    if "pan" in m:
        return pos, _v(tgt.x + rx * turn * sign, tgt.y + ry * turn * sign, tgt.z)
    if "track" in m or "truck" in m:
        sx, sy = rx * amount * sign, ry * amount * sign
        return _v(pos.x + sx, pos.y + sy, pos.z), _v(tgt.x + sx, tgt.y + sy, tgt.z)
    if "tilt" in m:
        dz = turn * (-1.0 if "down" in m else 1.0)
        return pos, _v(tgt.x, tgt.y, tgt.z + dz)
    if "crane" in m or "boom" in m:
        dz = CRANE_M * (-1.0 if "down" in m else 1.0)
        return _v(pos.x, pos.y, pos.z + dz), tgt
    return None


def camera_rig(
    layout: LocationLayout,
    camera: CameraInput,
    focus: Vec3 | None,
    duration_s: float,
    aspect: Aspect = "16:9",
    master: CameraRig | None = None,
) -> CameraRig:
    """Start/end camera pose for one clip (`focus.z` = subject height, None = room centre;
    `master` = calibrated plate camera, else the synthetic master)."""
    base = master_rig(layout, aspect, master)
    size = camera.shot_size
    close = size in _SIZES
    pos, tgt = _close(layout, base, size, focus) if close else _wide(base, size)
    pos = _angled(pos, tgt, camera.angle)
    end = _moved(pos, tgt, camera.movement, duration_s)
    return CameraRig(
        position=pos,
        target=tgt,
        end_position=end[0] if end else None,
        end_target=end[1] if end else None,
        lens_mm=float(camera.lens_mm) if close else base.lens_mm,
        sensor_width_mm=base.sensor_width_mm,
        shift_x=0.0 if close else base.shift_x,
        shift_y=0.0 if close else base.shift_y,
    )

"""Pure procedural motion: blocking keys -> per-sample joint angles, bob, lean, squash.

Joint angles are rotations about the joint's local X in degrees (negative = swing forward,
towards the facing direction -Y). Walk phase advances with distance travelled (stride ~0.65
of body height per step) so feet do not skate; amplitude scales with speed. Pose changes
blend over BLEND_S after each key. Samples are taken at SAMPLE_HZ and keyed with bezier.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Any

SAMPLE_HZ = 8
BLEND_S = 0.35
STRIDE_PER_HEIGHT = 1.3  # one full gait cycle (two steps) per 1.3 body heights
WALK_SPEED_REF = 1.4  # m/s at which swing amplitude reaches WALK_AMP_DEG
WALK_AMP_DEG = 30.0
Keys = list[dict[str, Any]]


@dataclass
class Pose:
    joints: dict[str, float] = field(default_factory=dict)
    bob: float = 0.0  # body z offset (unit-height units)
    lean: float = 0.0  # body rot-x degrees (+ = lean forward)
    squash: float = 1.0  # body scale z


@dataclass(frozen=True)
class MotionSample:
    t: float
    pose: Pose


def unwrap_angles(degrees: list[float]) -> list[float]:
    """Shift each heading by 360k so consecutive keys turn the short way round."""
    out: list[float] = []
    for deg in degrees:
        if out:
            deg = out[-1] + ((deg - out[-1] + 180.0) % 360.0 - 180.0)
        out.append(deg)
    return out


def _pos(key: dict[str, Any]) -> tuple[float, float]:
    p = key.get("position") or {}
    return (float(p.get("x", 0.0)), float(p.get("y", 0.0)))


def cumulative_distance(keys: Keys) -> list[float]:
    """Path length (XY, linear between keys) at each key."""
    out = [0.0]
    for a, b in zip(keys, keys[1:]):
        (ax, ay), (bx, by) = _pos(a), _pos(b)
        out.append(out[-1] + math.hypot(bx - ax, by - ay))
    return out


def walk_pose(archetype: str, phase: float, amp: float) -> Pose:
    """Gait at `phase` (radians) with swing amplitude `amp` degrees."""
    s = math.sin(phase)
    bob = 0.025 * (amp / WALK_AMP_DEG) * (1 - math.cos(2 * phase)) / 2
    if archetype == "quadruped":
        j = {
            "hip_fl": amp * s,
            "hip_br": amp * s,
            "hip_fr": -amp * s,
            "hip_bl": -amp * s,
            "tail": 15 * s,
        }
        return Pose(joints=j, bob=bob)
    if archetype == "creature":
        return Pose(bob=2 * bob, squash=1 - 0.08 * abs(s))
    arm = 0.6 if archetype == "human" else 0.4
    j = {
        "hip_l": amp * s,
        "hip_r": -amp * s,
        "shoulder_l": -arm * amp * s,
        "shoulder_r": arm * amp * s,
    }
    return Pose(joints=j, bob=bob)


def static_pose(archetype: str, pose: str, reach_deg: float) -> Pose:
    """Target pose for non-walk poses (stand/reach/point/push/crouch/sit)."""
    biped = archetype in ("human", "small_robot")
    if pose in ("reach", "point") and biped:
        return Pose(joints={"shoulder_r": -(90.0 if pose == "point" else reach_deg)})
    if pose == "push":
        arms = {"shoulder_l": -85.0, "shoulder_r": -85.0} if biped else {}
        return Pose(joints=arms, lean=14.0)
    if pose == "crouch":
        return Pose(
            joints={"hip_l": -30.0, "hip_r": -30.0} if biped else {},
            squash=0.7,
            lean=8.0,
        )
    if pose == "sit":
        if biped:
            return Pose(joints={"hip_l": -85.0, "hip_r": -85.0}, bob=-0.2)
        return Pose(joints={"hip_bl": -70.0, "hip_br": -70.0}, lean=-18.0, squash=0.85)
    if pose == "reach":
        return Pose(lean=10.0, squash=1.08)
    return Pose()


def reach_angle(
    shoulder_z: float,
    char_xy: tuple[float, float],
    target: tuple[float, float, float] | None,
) -> float:
    """Arm raise (deg from hanging) aiming at a target point; 75 when no target."""
    if target is None:
        return 75.0
    horiz = math.hypot(target[0] - char_xy[0], target[1] - char_xy[1])
    elevation = math.degrees(math.atan2(target[2] - shoulder_z, max(horiz, 0.05)))
    return min(max(90.0 + elevation, 30.0), 170.0)


def blend(a: Pose, b: Pose, w: float) -> Pose:
    """Linear blend a -> b (w in [0, 1]); missing joints count as 0."""
    names = set(a.joints) | set(b.joints)
    joints = {
        n: a.joints.get(n, 0.0) * (1 - w) + b.joints.get(n, 0.0) * w for n in names
    }
    return Pose(
        joints,
        _mix(a.bob, b.bob, w),
        _mix(a.lean, b.lean, w),
        _mix(a.squash, b.squash, w),
    )


def _mix(x: float, y: float, w: float) -> float:
    return x * (1 - w) + y * w


@dataclass(frozen=True)
class MotionContext:
    archetype: str
    height: float
    keys: Keys
    times: list[float]
    dist: list[float]
    targets: dict[int, tuple[float, float, float]]  # key index -> reach target (world)


def _key_pose(ctx: MotionContext, idx: int, t: float) -> Pose:
    """Pose demanded by key `idx` at time t (walk uses distance-driven phase)."""
    key = ctx.keys[idx]
    name = str(key.get("pose", "stand"))
    if name != "walk":
        reach = reach_angle(0.8 * ctx.height, _pos(key), ctx.targets.get(idx))
        return static_pose(ctx.archetype, name, reach)
    nxt = min(idx + 1, len(ctx.keys) - 1)
    span = max(ctx.times[nxt] - ctx.times[idx], 1e-6)
    seg = ctx.dist[nxt] - ctx.dist[idx]
    speed = seg / span if nxt != idx else 0.0
    travelled = ctx.dist[idx] + seg * min(max((t - ctx.times[idx]) / span, 0.0), 1.0)
    stride = STRIDE_PER_HEIGHT * ctx.height
    phase = 2 * math.pi * (travelled / stride if speed > 0.05 else t)
    amp = min(max(WALK_AMP_DEG * speed / WALK_SPEED_REF, 8.0), 38.0)
    return walk_pose(ctx.archetype, phase, amp)


def pose_at(ctx: MotionContext, t: float) -> Pose:
    """Active key's pose, blended in from the previous key's pose over BLEND_S."""
    idx = max(bisect.bisect_right(ctx.times, t) - 1, 0)
    current = _key_pose(ctx, idx, t)
    since = t - ctx.times[idx]
    if idx == 0 or since >= BLEND_S:
        return current
    return blend(_key_pose(ctx, idx - 1, t), current, since / BLEND_S)


def sample_motion(
    archetype: str,
    height: float,
    keys: Keys,
    duration: float,
    targets: dict[int, tuple[float, float, float]] | None = None,
) -> list[MotionSample]:
    """Pose samples at SAMPLE_HZ over [0, duration] for one character track."""
    if not keys:
        return []
    ordered = sorted(keys, key=lambda k: float(k.get("t", 0.0)))
    ctx = MotionContext(archetype, height, ordered, [float(k.get("t", 0.0)) for k in ordered],
                        cumulative_distance(ordered), targets or {})  # fmt: skip
    count = int(math.floor(duration * SAMPLE_HZ + 1e-9)) + 1
    return [
        MotionSample(i / SAMPLE_HZ, pose_at(ctx, i / SAMPLE_HZ)) for i in range(count)
    ]

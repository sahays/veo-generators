"""Beat walks (pure): actors walk to what they act on even when plan x does not move.

The 2D planner only moves a character when its beat target has a plate x (set pieces). In
3D every object has a position, so for each beat whose actor's plan x stays put while the
target has a floor position (a set piece's front, a prop standing on one, or a resting
prop's home), the actor walks there: leaves at `t_start`, arrives by `ARRIVE_FRAC` of the
beat, never faster than `WALK_SPEED` m/s, then follows its plan path offset by the arrival
point; seconds at the target during the beat are marked `reach`. An actor whose first beat
says it enters ("enters", "walks in", ...) starts at the side wall nearest its destination
and walks in. Deterministic; O(beats × seconds).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ...keyframes.plan.models import BeatSpan, KeyframePlan, PlanInput
from .props import resting_position
from .stage import FRONT_GAP, WALL_PAD, Stage

WALK_SPEED: Final[float] = 1.2
ARRIVE_FRAC: Final[float] = 0.7
ARRIVE_EPS: Final[float] = 0.35
AT_TARGET: Final[float] = 0.1
PLAN_MOVE_EPS: Final[float] = 0.02
STAND_GAP: Final[float] = 0.45
_ENTER: Final[tuple[str, ...]] = (
    "enter",
    "walks in",
    "walk in",
    "comes in",
    "steps in",
    "arrives",
)
XY = tuple[float, float]
Paths = dict[str, list[XY]]


@dataclass(frozen=True)
class Walk:
    actor: str
    i0: int
    i1: int
    arrive: float
    dest: XY
    reach: bool
    speed: float = WALK_SPEED


def stand_point(
    stage: Stage, inp: PlanInput, plan: KeyframePlan, beat: BeatSpan, near: XY
) -> XY | None:
    """Where the actor stands to act on the beat target (None: character / unknown)."""
    target = beat.target_id or ""
    frame = plan.at(math.floor(beat.t_start))
    if not target or any(c.entity_id == target for c in inp.cast):
        return None
    piece = stage.anchor_piece(frame, target)
    if piece is not None:
        half = max(piece.size.x / 2 - 0.2, 0.0)
        x = min(max(near[0], piece.position.x - half), piece.position.x + half)
        return round(x, 3), stage.clamp_y(
            piece.position.y - piece.size.y / 2 - FRONT_GAP
        )
    rest = resting_position(stage, frame, target)
    return (rest.x, stage.clamp_y(rest.y - STAND_GAP)) if rest else None


def _entering(beat: BeatSpan) -> bool:
    action = beat.action.lower()
    return any(k in action for k in _ENTER)


def _plan_moves(base: Sequence[XY], i0: int, i1: int) -> bool:
    xs = [p[0] for p in base[i0 : i1 + 1]]
    return bool(xs) and max(xs) - min(xs) > PLAN_MOVE_EPS


def _span(beat: BeatSpan, n: int) -> tuple[int, int]:
    i0 = min(max(math.floor(beat.t_start), 0), n - 1)
    return i0, min(max(math.ceil(beat.t_end), i0), n - 1)


def _walk(path: list[XY], base: Sequence[XY], w: Walk) -> list[XY]:
    """Path from `i0`: interpolate to `dest` by `arrive`, then follow base + offset, capped."""
    start, n = path[w.i0], len(path)
    ai = min(math.ceil(w.arrive), n - 1)
    out = path[: w.i0 + 1]
    for i in range(w.i0 + 1, n):
        if i < w.arrive:
            f = (i - w.i0) / (w.arrive - w.i0)
            want = (
                start[0] + (w.dest[0] - start[0]) * f,
                start[1] + (w.dest[1] - start[1]) * f,
            )
        else:
            want = (
                w.dest[0] + base[i][0] - base[ai][0],
                w.dest[1] + base[i][1] - base[ai][1],
            )
        px, py = out[-1]
        dist = math.hypot(want[0] - px, want[1] - py)
        k = 1.0 if dist <= w.speed else w.speed / dist
        out.append(
            (round(px + (want[0] - px) * k, 3), round(py + (want[1] - py) * k, 3))
        )
    return out


def _edge(stage: Stage, dest: XY) -> XY:
    side = -1.0 if dest[0] <= 0 else 1.0
    return round(side * (stage.layout.room.width / 2 - WALL_PAD), 3), dest[1]


def _plan_walk(
    stage: Stage,
    inp: PlanInput,
    plan: KeyframePlan,
    beat: BeatSpan,
    path: list[XY],
    base: Sequence[XY],
    enters: bool,
    speed: float = WALK_SPEED,
) -> Walk | None:
    i0, i1 = _span(beat, len(path))
    target = stand_point(stage, inp, plan, beat, path[i0])
    dest = target or (base[i1] if enters else None)
    if dest is None or (_plan_moves(base, i0, i1) and not enters):
        return None
    if enters:
        path[: i0 + 1] = [_edge(stage, dest)] * (i0 + 1)
    if math.dist(path[i0], dest) < ARRIVE_EPS:
        return None
    arrive = i0 + max(ARRIVE_FRAC * (beat.t_end - beat.t_start), 1.0)
    return Walk(beat.actor_id, i0, i1, arrive, dest, target is not None, speed)


def bound_speed(path: Sequence[XY], vmax: float) -> list[XY]:
    """`path` (one point per second) with every step clamped to `vmax` metres."""
    out: list[XY] = list(path[:1])
    for want in path[1:]:
        px, py = out[-1]
        dist = math.hypot(want[0] - px, want[1] - py)
        k = 1.0 if dist <= vmax else vmax / dist
        out.append(
            (round(px + (want[0] - px) * k, 3), round(py + (want[1] - py) * k, 3))
        )
    return out


def apply_walks(
    stage: Stage,
    inp: PlanInput,
    plan: KeyframePlan,
    base: Mapping[str, list[XY]],
    speeds: Mapping[str, float] | None = None,
) -> tuple[Paths, set[tuple[str, int]]]:
    """Paths with beat walks applied, and the (character, second) pairs that reach.
    A beat walk never exceeds min(WALK_SPEED, the actor's body speed bound)."""
    paths: Paths = {cid: list(p) for cid, p in base.items()}
    reach: set[tuple[str, int]] = set()
    seen: set[str] = set()
    for beat in inp.beats:
        path = paths.get(beat.actor_id)
        if path is None:
            continue
        enters = beat.actor_id not in seen and _entering(beat)
        seen.add(beat.actor_id)
        speed = min(WALK_SPEED, (speeds or {}).get(beat.actor_id, WALK_SPEED))
        walk = _plan_walk(
            stage, inp, plan, beat, path, base[beat.actor_id], enters, speed
        )
        if walk is None:
            continue
        paths[walk.actor] = path = _walk(path, base[walk.actor], walk)
        if walk.reach:
            reach |= {
                (walk.actor, i)
                for i in range(walk.i0, walk.i1 + 1)
                if math.dist(path[i], walk.dest) < AT_TARGET
            }
    return paths, reach

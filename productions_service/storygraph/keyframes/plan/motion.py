"""Per-second character positions: beat anchors, interpolation and bounded displacement (pure).

Anchors: every character starts at its carried-over x (`PlanInput.start_x`, i.e. where the
previous clip ended) or its cast screen column. When a beat's actor acts on an entity whose
position the scene layout knows (furniture / placed props on the locked plate), the actor's
anchor at the end of that beat is beside that entity (on the side it approaches from).
Between anchors x is linearly interpolated per second, then rate-limited so no character
moves more than `MAX_STEP_X` frame widths in one second — in-between seconds show
in-between positions and nobody teleports. O(seconds × characters).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from typing import Final

from .models import PlanInput

COLUMN_X: Final[dict[str, float]] = {
    "left": 0.22,
    "center": 0.5,
    "foreground": 0.5,
    "background": 0.5,
    "right": 0.78,
}
MAX_STEP_X: Final[float] = 0.18
BESIDE_GAP: Final[float] = 0.08


def start_positions(inp: PlanInput) -> dict[str, float]:
    return {
        c.entity_id: inp.start_x.get(c.entity_id, COLUMN_X[c.position])
        for c in inp.cast
    }


def _beside(target_x: float, from_x: float) -> float:
    """Stand next to the target on the side the character comes from."""
    side = -BESIDE_GAP if from_x <= target_x else BESIDE_GAP
    return min(0.95, max(0.05, target_x + side))


def anchors(inp: PlanInput) -> dict[str, list[tuple[float, float]]]:
    """`character -> [(second, x)]` anchors in time order (t=0 first).

    The actor holds still until its beat starts, then reaches the target (a layout entity, or
    another character's latest anchor) by the beat's end."""
    out = {cid: [(0.0, x)] for cid, x in start_positions(inp).items()}
    for beat in inp.beats:
        track = out.get(beat.actor_id)
        target = beat.target_id or ""
        other = out.get(target)
        target_x = inp.layout.get(target, other[-1][1] if other else None)
        if track is None or target_x is None or target == beat.actor_id:
            continue
        hold_t, hold_x = track[-1]
        if beat.t_start > hold_t:
            track.append((beat.t_start, hold_x))
        track.append((max(beat.t_end, track[-1][0]), _beside(target_x, hold_x)))
    return out


def interpolate(points: Sequence[tuple[float, float]], t: float) -> float:
    """Piecewise-linear x at `t` (held constant outside the anchor range)."""
    times = [p[0] for p in points]
    i = bisect_right(times, t)
    if i == 0:
        return points[0][1]
    if i >= len(points):
        return points[-1][1]
    (t0, x0), (t1, x1) = points[i - 1], points[i]
    return x0 if t1 <= t0 else x0 + (x1 - x0) * (t - t0) / (t1 - t0)


def rate_limit(xs: Sequence[float], max_step: float = MAX_STEP_X) -> list[float]:
    """Forward pass: each second moves at most `max_step` toward the interpolated target."""
    out: list[float] = []
    for x in xs:
        prev = out[-1] if out else x
        out.append(round(prev + max(-max_step, min(max_step, x - prev)), 3))
    return out


def tracks(inp: PlanInput, last_t: int) -> dict[str, list[float]]:
    """`character -> [x at t=0..last_t]` (interpolated between anchors, rate-limited)."""
    return {
        cid: rate_limit([interpolate(points, float(t)) for t in range(last_t + 1)])
        for cid, points in anchors(inp).items()
    }

"""Joint camera + room-box least squares (deterministic Levenberg-Marquardt, numpy).

Residuals (pixels): VLM corner positions, distances of detected line-segment endpoints to
the projected box edge they were snapped to, the depth vanishing point, and weak log-priors
on the metric scale (eye height, room width/depth/height). A single image fixes only the
box's shape relative to the camera; the priors pick the metric scale and any dimension the
plate does not show. Huber IRLS keeps a wrong corner from dragging the fit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property
from typing import Final

import numpy as np
from numpy.typing import NDArray

from .geometry import EDGES, IDX, Floats, Frame, depth_vp, edge_lines, project_corners

HUBER_FRAC: Final[float] = 0.01  # of the image width
PRIOR_PX_FRAC: Final[float] = 0.02  # residual (of width) of a prior off by a factor e
LO: Final[Floats] = np.array(
    [-20, -60, 0.2, -1.2, -0.6, 0.2, -0.5, -0.5, 1.0, 0.8, 1.0]
)
HI: Final[Floats] = np.array([20, 30, 6.0, 0.6, 0.6, 5.0, 0.5, 0.5, 40.0, 40.0, 10.0])
STEPS: Final[Floats] = np.array(
    [1e-4, 1e-4, 1e-4, 1e-5, 1e-5, 1e-5, 1e-5, 1e-5, 1e-4, 1e-4, 1e-4]
)
MIN_WALL_GAP: Final[float] = 0.3  # camera stays this far in front of the back wall


@dataclass(frozen=True)
class PointObs:
    corner: str
    u: float
    v: float
    weight: float = 1.0


@dataclass(frozen=True)
class LineObs:
    edge: str
    p0: tuple[float, float]
    p1: tuple[float, float]
    weight: float = 1.0


@dataclass(frozen=True)
class Problem:
    frame: Frame
    free: tuple[str, ...]
    points: Sequence[PointObs] = ()
    lines: Sequence[LineObs] = ()
    vp: tuple[float, float] | None = None
    vp_weight: float = 0.0
    priors: Mapping[str, float] = field(default_factory=dict)

    @cached_property
    def line_arrays(self) -> tuple[NDArray[np.int64], Floats, Floats]:
        """(edge index per endpoint, homogeneous endpoints (2N,3), weight per endpoint)."""
        order = {name: i for i, name in enumerate(EDGES)}
        idx = [order[ln.edge] for ln in self.lines for _ in (0, 1)]
        pts = [[*p, 1.0] for ln in self.lines for p in (ln.p0, ln.p1)]
        wts = [ln.weight for ln in self.lines for _ in (0, 1)]
        return (
            np.asarray(idx, dtype=np.int64),
            np.asarray(pts, dtype=float).reshape(-1, 3),
            np.asarray(wts, dtype=float),
        )


def residuals(v: Floats, prob: Problem) -> Floats:
    """Weighted residual vector (pixels) of parameter vector `v`."""
    out: list[Floats] = []
    proj = project_corners(v, prob.frame)
    pts = [
        ((proj[p.corner][0] - p.u) * p.weight, (proj[p.corner][1] - p.v) * p.weight)
        for p in prob.points
    ]
    out.append(np.asarray(pts, dtype=float).ravel())
    if prob.lines:
        idx, hom, wts = prob.line_arrays
        table = np.stack(list(edge_lines(v, prob.frame).values()))
        out.append((table[idx] * hom).sum(axis=1) * wts)
    if prob.vp is not None and prob.vp_weight > 0:
        u, w = depth_vp(v, prob.frame)
        out.append(np.array([u - prob.vp[0], w - prob.vp[1]]) * prob.vp_weight)
    scale = PRIOR_PX_FRAC * prob.frame.width
    priors = sorted(prob.priors.items())
    out.append(
        np.array([scale * math.log(max(v[IDX[n]], 1e-6) / val) for n, val in priors])
    )
    return np.concatenate(out)


def _robust(r: Floats, width: int) -> Floats:
    """Huber IRLS weights (sqrt), k = HUBER_FRAC * width."""
    k = HUBER_FRAC * width
    return np.sqrt(np.minimum(1.0, k / np.maximum(np.abs(r), 1e-12)))


def _jacobian(v: Floats, prob: Problem, cols: list[int]) -> Floats:
    """Central-difference Jacobian over the free columns."""
    jac = []
    for i in cols:
        dv = np.zeros_like(v)
        dv[i] = STEPS[i] * max(1.0, abs(v[i]))
        jac.append((residuals(v + dv, prob) - residuals(v - dv, prob)) / (2 * dv[i]))
    return np.stack(jac, axis=1)


def _cost(v: Floats, prob: Problem, w: Floats) -> float:
    r = residuals(v, prob) * w
    return float(r @ r)


def _bounded(x: Floats) -> Floats:
    """Clip into LO/HI and keep the camera in front of the back wall."""
    out = np.clip(x, LO, HI)
    out[IDX["cam_y"]] = min(out[IDX["cam_y"]], out[IDX["depth"]] - MIN_WALL_GAP)
    return out


def _robust_cost(v: Floats, prob: Problem) -> float:
    """Huber-like cost: r^2 inside the IRLS threshold, k|r| outside."""
    r = residuals(v, prob)
    r = r * _robust(r, prob.frame.width)
    return float(r @ r)


def _lm_step(
    x: Floats, prob: Problem, cols: list[int], lam: float
) -> tuple[Floats | None, float, float]:
    """One damped step (None when no damping level lowers the IRLS cost)."""
    r = residuals(x, prob)
    w = _robust(r, prob.frame.width)
    cost = float((r * w) @ (r * w))
    jac = _jacobian(x, prob, cols) * w[:, None]
    a, g = jac.T @ jac, jac.T @ (r * w)
    while lam < 1e8:
        step = np.linalg.solve(a + lam * (np.diag(np.diag(a)) + 1e-9), -g)
        xn = x.copy()
        xn[cols] = x[cols] + step
        xn = _bounded(xn)
        new = _cost(xn, prob, w)
        if new < cost:
            return xn, max(lam / 3, 1e-7), cost - new
        lam *= 4
    return None, lam, 0.0


def solve(prob: Problem, x0: Floats, iters: int = 80) -> tuple[Floats, float]:
    """Levenberg-Marquardt from `x0` over `prob.free` (bounded); (x, robust cost)."""
    cols = [IDX[n] for n in prob.free]
    x, lam = _bounded(x0.astype(float)), 1e-2
    for _ in range(iters):
        xn, lam, gain = _lm_step(x, prob, cols, lam)
        if xn is None:
            break
        x = xn
        if gain < 1e-9 * max(_robust_cost(x, prob), 1.0):
            break
    return x, _robust_cost(x, prob)


def best_of(prob: Problem, starts: Sequence[Floats]) -> tuple[Floats, float]:
    """Lowest-cost solution over deterministic starting points (first wins ties)."""
    best: tuple[Floats, float] | None = None
    for x0 in starts:
        x, cost = solve(prob, x0)
        if best is None or cost < best[1] - 1e-9:
            best = (x, cost)
    if best is None:
        raise ValueError("best_of needs at least one start")
    return best


def rms(values: Sequence[float]) -> float:
    return float(math.sqrt(sum(x * x for x in values) / len(values))) if values else 0.0


def point_errors(v: Floats, prob: Problem) -> list[float]:
    """Unweighted pixel distance of every corner observation to its projection."""
    proj = project_corners(v, prob.frame)
    return [math.hypot(proj[p.corner][0] - p.u, proj[p.corner][1] - p.v)
            for p in prob.points]  # fmt: skip


def line_errors(v: Floats, prob: Problem) -> list[float]:
    """Unweighted pixel distance of every snapped segment endpoint to its edge line."""
    lines = edge_lines(v, prob.frame)
    return [
        abs(lines[ln.edge] @ np.array([x, y, 1.0]))
        for ln in prob.lines
        for x, y in (ln.p0, ln.p1)
    ]

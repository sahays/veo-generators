"""Deterministic line-segment detection and vanishing points (pure numpy, O(pixels)).

`detect_segments`: thin Sobel edges (`edges.thin_edges`) vote into a (theta, rho) Hough
accumulator only at their own gradient orientation (+-1 bin), so the vote costs O(edge pixels)
instead of O(edge pixels * thetas). The strongest peaks are walked greedily: their supporting,
orientation-consistent pixels are split into gap-free runs, and each long run becomes one
segment (claimed pixels never vote for a later line). `vanishing_point` is a robust (IRLS)
least-squares intersection of the segments consistent with a starting guess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from .edges import Gray, thin_edges

N_THETA: Final[int] = 180
MAX_PEAKS: Final[int] = 80
LINE_TOL_PX: Final[float] = 1.5
ORIENT_TOL_DEG: Final[float] = 6.0
GAP_FRAC: Final[float] = 0.012
MIN_LEN_FRAC: Final[float] = 0.035
VP_GATE_DEG: Final[float] = 2.5
Floats = NDArray[np.float64]


@dataclass(frozen=True)
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def length(self) -> float:
        return math.hypot(self.x1 - self.x0, self.y1 - self.y0)

    def scaled(self, k: float) -> Segment:
        """Same segment in an image `k` times larger (pixel-centre convention)."""

        def s(c: float) -> float:
            return (c + 0.5) * k - 0.5

        return Segment(s(self.x0), s(self.y0), s(self.x1), s(self.y1))


@dataclass(frozen=True)
class _Pixels:
    xs: Floats
    ys: Floats
    theta: Floats  # gradient (= line normal) orientation in [0, pi)


def _edge_pixels(gray: Gray) -> _Pixels:
    mask, gx, gy = thin_edges(gray)
    ys, xs = np.nonzero(mask)
    theta = np.arctan2(gy[ys, xs], gx[ys, xs]) % math.pi
    return _Pixels(xs.astype(np.float64), ys.astype(np.float64), theta.astype(float))


def _accumulate(px: _Pixels, diag: int) -> NDArray[np.int64]:
    """(N_THETA, 2*diag+1) vote counts; each pixel votes at its own theta +-1 bin."""
    base = np.round(px.theta / math.pi * N_THETA).astype(np.int64)
    acc = np.zeros(N_THETA * (2 * diag + 1), dtype=np.int64)
    for off in (-1, 0, 1):
        t = (base + off) % N_THETA
        ang = t * math.pi / N_THETA
        rho = np.round(px.xs * np.cos(ang) + px.ys * np.sin(ang)).astype(np.int64)
        acc += np.bincount(t * (2 * diag + 1) + rho + diag, minlength=acc.size)
    return acc.reshape(N_THETA, 2 * diag + 1)


def _peaks(acc: NDArray[np.int64], min_votes: int) -> list[tuple[int, int]]:
    """Local maxima (5x5, theta wraps) with >= `min_votes`, strongest first."""
    wrapped = np.concatenate([acc[-2:], acc, acc[:2]])
    local = np.ones(acc.shape, dtype=bool)
    for dt in range(-2, 3):
        rows = wrapped[2 + dt : 2 + dt + acc.shape[0]]
        for dr in range(-2, 3):
            local &= acc >= np.roll(rows, dr, axis=1)
    ts, rs = np.nonzero(local & (acc >= min_votes))
    order = np.lexsort((rs, ts, -acc[ts, rs]))[:MAX_PEAKS]
    return [(int(ts[i]), int(rs[i])) for i in order]


def _runs(t: Floats, gap: float, min_len: float) -> list[tuple[int, int]]:
    """[start, end) index ranges of sorted `t` without gaps > `gap`, spanning >= min_len."""
    if t.size == 0:
        return []
    cuts = np.nonzero(np.diff(t) > gap)[0] + 1
    bounds = np.concatenate([[0], cuts, [t.size]])
    return [
        (int(a), int(b))
        for a, b in zip(bounds[:-1], bounds[1:], strict=True)
        if t[b - 1] - t[a] >= min_len
    ]


def _fit(xs: Floats, ys: Floats) -> Segment:
    """Total-least-squares line through the run, clipped to its extent."""
    cx, cy = float(xs.mean()), float(ys.mean())
    cov = np.cov(np.stack([xs - cx, ys - cy]))
    evals, evecs = np.linalg.eigh(cov)
    dx, dy = evecs[:, int(np.argmax(evals))]
    t = (xs - cx) * dx + (ys - cy) * dy
    return Segment(
        cx + dx * t.min(), cy + dy * t.min(), cx + dx * t.max(), cy + dy * t.max()
    )


def _select(px: _Pixels, free: NDArray[np.bool_], ang: float, rho: float,
            tol: float) -> NDArray[np.int64]:  # fmt: skip
    """Free pixels within `tol` px of line (ang, rho) whose gradient agrees with it."""
    c, s = math.cos(ang), math.sin(ang)
    dtheta = np.abs((px.theta - ang + math.pi / 2) % math.pi - math.pi / 2)
    near = np.abs(px.xs * c + px.ys * s - rho) <= tol
    return np.nonzero(free & near & (dtheta <= math.radians(ORIENT_TOL_DEG)))[0]


def _refit(px: _Pixels, idx: NDArray[np.int64]) -> tuple[float, float]:
    """(normal angle in [0, pi), rho) of the TLS line through the pixels."""
    seg = _fit(px.xs[idx], px.ys[idx])
    ang = math.atan2(seg.x1 - seg.x0, -(seg.y1 - seg.y0)) % math.pi
    return ang, seg.x0 * math.cos(ang) + seg.y0 * math.sin(ang)


def _walk(px: _Pixels, peak: tuple[int, int], diag: int, free: NDArray[np.bool_],
          width: int) -> list[Segment]:  # fmt: skip
    """Segments along one Hough peak from still-unclaimed pixels (claims them)."""
    ang, rho = peak[0] * math.pi / N_THETA, float(peak[1] - diag)
    min_len = MIN_LEN_FRAC * width
    for tol in (3 * LINE_TOL_PX, LINE_TOL_PX):
        idx = _select(px, free, ang, rho, tol)
        if idx.size < min_len / 2:
            return []
        ang, rho = _refit(px, idx)
    idx = _select(px, free, ang, rho, LINE_TOL_PX)
    t = -px.xs[idx] * math.sin(ang) + px.ys[idx] * math.cos(ang)
    order = np.argsort(t, kind="stable")
    idx, t = idx[order], t[order]
    out: list[Segment] = []
    for a, b in _runs(t, GAP_FRAC * width, min_len):
        run = idx[a:b]
        free[run] = False
        out.append(_fit(px.xs[run], px.ys[run]))
    return out


def detect_segments(gray: Gray) -> list[Segment]:
    """Straight segments (pixel coords of `gray`), longest first; [] for a featureless image."""
    h, w = gray.shape
    px = _edge_pixels(gray)
    if px.xs.size == 0:
        return []
    diag = int(math.ceil(math.hypot(h, w)))
    peaks = _peaks(_accumulate(px, diag), int(MIN_LEN_FRAC * w))
    free = np.ones(px.xs.size, dtype=bool)
    segments: list[Segment] = []
    for peak in peaks:
        segments.extend(_walk(px, peak, diag, free, w))
    return sorted(segments, key=lambda sg: (-sg.length, sg.x0, sg.y0))


def _lines(segments: list[Segment]) -> tuple[Floats, Floats, Floats, Floats]:
    """(unit normals (N,2), offsets c with n.p = c, midpoints (N,2), lengths)."""
    p0 = np.array([[sg.x0, sg.y0] for sg in segments], dtype=float)
    p1 = np.array([[sg.x1, sg.y1] for sg in segments], dtype=float)
    d = p1 - p0
    length = np.hypot(d[:, 0], d[:, 1])
    n = np.stack([-d[:, 1], d[:, 0]], axis=1) / length[:, None]
    return n, (n * p0).sum(axis=1), (p0 + p1) / 2, length


def vanishing_point(
    segments: list[Segment], guess: tuple[float, float], iters: int = 6
) -> tuple[tuple[float, float] | None, int]:
    """(robust VP of the segments pointing at `guess`, inlier count); None if < 4 inliers."""
    if len(segments) < 2:
        return None, 0
    n, c, mid, length = _lines(segments)
    vp = np.array(guess, dtype=float)
    inliers = np.zeros(len(segments), dtype=bool)
    for _ in range(iters):
        to_vp = vp - mid
        dist = np.hypot(to_vp[:, 0], to_vp[:, 1]) + 1e-9
        sin_err = np.abs((n * to_vp).sum(axis=1)) / dist
        inliers = sin_err <= math.sin(math.radians(VP_GATE_DEG))
        if inliers.sum() < 4:
            return None, int(inliers.sum())
        w = length[inliers]
        a = (n[inliers] * w[:, None]).T @ n[inliers]
        if abs(np.linalg.det(a)) < 1e-9:
            return None, int(inliers.sum())
        vp = np.linalg.solve(a, (n[inliers] * (w * c[inliers])[:, None]).sum(axis=0))
    return (float(vp[0]), float(vp[1])), int(inliers.sum())

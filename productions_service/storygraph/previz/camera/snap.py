"""Snap detected segments to the projected room-box edges and seed the solver (pure numpy).

`snap_segments` assigns each segment to at most one box edge: nearly parallel (< MAX_ANGLE),
both endpoints within `tol_px` of the projected edge line and overlapping its projected
extent. Vectorised over (segments x edges): O(segments * 11). `initial_guesses` turns the VLM
corners into deterministic starting points for a few focal lengths.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Final

import numpy as np

from .geometry import (
    EDGES,
    Floats,
    Frame,
    corner_depths,
    edge_lines,
    params,
    project_corners,
)  # fmt: skip
from .lines import Segment
from .solve import LineObs

MAX_ANGLE_DEG: Final[float] = 4.0
OVERLAP_SLACK: Final[float] = 0.15  # fraction of the edge length past either end
FOCAL_STARTS: Final[tuple[float, ...]] = (0.6, 0.9, 1.35, 2.0)
REF_LEN_FRAC: Final[float] = 0.05


def _overlap(mid: Floats, v: Floats, frame: Frame) -> Floats:
    """(M, E) True where a segment midpoint projects inside an edge's extent (+ slack);
    always True for an edge with a corner behind the camera (its extent is unbounded)."""
    ends, depth = project_corners(v, frame), corner_depths(v)
    cols = []
    for a, b in EDGES.values():
        if min(depth[a], depth[b]) <= 0:
            cols.append(np.ones(len(mid), dtype=bool))
            continue
        pa, pb = np.array(ends[a]), np.array(ends[b])
        d = pb - pa
        t = ((mid - pa) @ d) / max(float(d @ d), 1e-9)
        cols.append((t >= -OVERLAP_SLACK) & (t <= 1 + OVERLAP_SLACK))
    return np.stack(cols, axis=1)


def snap_segments(
    v: Floats, frame: Frame, segments: Sequence[Segment], tol_px: float
) -> list[LineObs]:
    """Line observations for the segments that lie on a projected box edge."""
    if not segments:
        return []
    names = list(EDGES)
    table = np.stack([edge_lines(v, frame)[n] for n in names])  # (E, 3)
    p0 = np.array([[s.x0, s.y0, 1.0] for s in segments])
    p1 = np.array([[s.x1, s.y1, 1.0] for s in segments])
    d0, d1 = np.abs(p0 @ table.T), np.abs(p1 @ table.T)
    seg_dir = p1[:, :2] - p0[:, :2]
    length = np.hypot(seg_dir[:, 0], seg_dir[:, 1])
    sin_angle = np.abs((seg_dir / length[:, None]) @ table[:, :2].T)
    mid = (p0[:, :2] + p1[:, :2]) / 2
    ok = (np.maximum(d0, d1) <= tol_px) & (
        sin_angle <= math.sin(math.radians(MAX_ANGLE_DEG))
    )
    ok &= _overlap(mid, v, frame)
    score = np.where(ok, d0 + d1, np.inf)
    best = np.argmin(score, axis=1)
    ref = REF_LEN_FRAC * frame.width
    return [
        LineObs(
            edge=names[int(best[i])],
            p0=(float(p0[i, 0]), float(p0[i, 1])),
            p1=(float(p1[i, 0]), float(p1[i, 1])),
            weight=float(np.clip(length[i] / ref, 0.3, 2.0)),
        )
        for i in range(len(segments))
        if np.isfinite(score[i, best[i]])
    ]


def _back_span(px: Mapping[str, tuple[float, float]]) -> tuple[float, float] | None:
    """(pixel width, centre u) of the back wall from its bottom or top corner pair."""
    for left, right in (("back_bl", "back_br"), ("back_tl", "back_tr")):
        if left in px and right in px:
            return px[right][0] - px[left][0], (px[right][0] + px[left][0]) / 2
    return None


def initial_guesses(
    px: Mapping[str, tuple[float, float]], priors: Mapping[str, float], frame: Frame
) -> list[Floats]:
    """One start per focal in FOCAL_STARTS, placed so the back wall spans its pixels."""
    span = _back_span(px)
    width, depth, eye = priors["width"], priors["depth"], priors["cam_h"]
    starts: list[Floats] = []
    for focal in FOCAL_STARTS:
        f_px = focal * frame.width
        dist = f_px * width / span[0] if span and span[0] > 1 else depth + 2.0
        cam_x = -(span[1] - frame.width / 2) * dist / f_px if span else 0.0
        pitch = 0.0
        if "back_bl" in px:
            below = math.atan2(eye, dist)
            pitch = math.atan2(px["back_bl"][1] - frame.height / 2, f_px) - below
        starts.append(
            params(cam_x=cam_x, cam_y=depth - dist, cam_h=eye, pitch=pitch,
                   focal=focal, width=width, depth=depth, height=priors["height"])
        )  # fmt: skip
    return starts

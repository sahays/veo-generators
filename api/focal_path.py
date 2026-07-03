"""Pan-path optimization for smart video reframing.

Pure math — no FFmpeg, no I/O. `l1_pan_path` solves the crop's pan trajectory
as an L1 optimization (holds and constant-velocity pans emerge from the
objective) on a discretized position×velocity grid. Used by
`reframe_plan.attach_keypoints`.
"""

import bisect
import math
from typing import List, Tuple


# ---------------------------------------------------------------------------
# L1 pan-path optimization (discretized DP)
#
# The camera-path literature (Grundmann et al., CVPR 2011 — YouTube's
# stabilizer) frames a good virtual-camera path as the minimizer of L1 costs on
# the path's derivatives: |x'| makes HOLDS cheap, |x''| makes CONSTANT-VELOCITY
# pans cheap, so the optimum is piecewise static/linear — exactly the alphabet
# the renderer's piecewise-linear x(t) expression can encode losslessly. The
# subject only constrains the path through a containment window (crop center
# must stay within ±contain_w of the subject), so detection jitter inside the
# window produces NO motion at all, and a walking subject produces one clean
# pan instead of a chase. Solved exactly on a discretized (position × velocity)
# grid: velocity states cap pan speed by construction.
# ---------------------------------------------------------------------------

PAN_GRID_SEC = 0.5  # trajectory sample spacing
PAN_POS_STEP = 0.01  # position quantum (frac of frame width; ~19px at 1920)
PAN_CONTAIN_WEIGHT = 60.0  # per frac outside the containment window (dominant)
PAN_PULL_WEIGHT = 0.08  # gentle pull toward center once inside the window
PAN_TRAVEL_WEIGHT = 0.15  # L1 on velocity: holds beat travel
PAN_SLOPE_WEIGHT = 1.2  # L1 on acceleration: few pan-slope changes (per frac/s)


def _interp_target(times: List[float], xs: List[float], t: float) -> float:
    """Linear interpolation of the subject series at t (held at the ends)."""
    if t <= times[0]:
        return xs[0]
    if t >= times[-1]:
        return xs[-1]
    i = min(bisect.bisect_right(times, t) - 1, len(times) - 2)
    t0, t1 = times[i], times[i + 1]
    if t1 == t0:
        return xs[i]
    f = (t - t0) / (t1 - t0)
    return xs[i] + (xs[i + 1] - xs[i]) * f


def _velocity_ladder(kmax: int) -> List[int]:
    """Sparse symmetric set of bins-per-step velocities up to ±kmax."""
    ks = {0}
    k = 1
    while k < kmax:
        ks.add(k)
        k = max(k + 1, int(round(k * 1.6)))
    ks.add(kmax)
    return sorted(ks | {-k for k in ks})


def l1_pan_path(
    points: List[dict],
    start: float,
    end: float,
    contain_w: float = 0.08,
    max_velocity: float = 0.15,
) -> List[Tuple[float, float]]:
    """Optimal piecewise-linear pan path for one segment. Returns [(t, x)].

    `points`: subject samples [{"time_sec", "x"}] (absolute time). The path
    minimizes containment violations (subject farther than `contain_w` from the
    crop center) + L1 travel + L1 slope changes, with speed hard-capped at
    `max_velocity` (frac of width / second). Keypoints are emitted only where
    the pan slope changes, so a static subject yields two keypoints and a
    walking subject yields a single clean pan.
    """
    dur = max(1e-3, end - start)
    n = max(2, int(math.ceil(dur / PAN_GRID_SEC)) + 1)
    dt = dur / (n - 1)
    pt_times = [p["time_sec"] for p in points]
    pt_xs = [max(0.0, min(1.0, p["x"])) for p in points]
    times = [start + i * dt for i in range(n)]
    targets = [_interp_target(pt_times, pt_xs, t) for t in times]

    lo = max(0.0, min(targets) - contain_w - 2 * PAN_POS_STEP)
    hi = min(1.0, max(targets) + contain_w + 2 * PAN_POS_STEP)
    nbins = max(2, int(round((hi - lo) / PAN_POS_STEP)) + 1)
    pos = [lo + b * PAN_POS_STEP for b in range(nbins)]
    kmax = max(1, int(max_velocity * dt / PAN_POS_STEP))
    ks = _velocity_ladder(kmax)
    slope_unit = PAN_POS_STEP / dt  # one bin-per-step in frac/s

    def emission(i: int, x: float) -> float:
        d = abs(x - targets[i])
        over = max(0.0, d - contain_w)
        inside_pull = max(0.0, d - contain_w * 0.5)
        return PAN_CONTAIN_WEIGHT * over + PAN_PULL_WEIGHT * inside_pull

    # cost[(b, k)] = best cost reaching position-bin b at step i, having moved
    # k bins on the last step. ptr for backtracking.
    cost = {(b, 0): emission(0, pos[b]) for b in range(nbins)}
    ptrs: List[dict] = []
    for i in range(1, n):
        nxt: dict = {}
        ptr: dict = {}
        for (b, k), c in cost.items():
            for k2 in ks:
                b2 = b + k2
                if not 0 <= b2 < nbins:
                    continue
                c2 = (
                    c
                    + PAN_TRAVEL_WEIGHT * abs(k2) * PAN_POS_STEP
                    + PAN_SLOPE_WEIGHT * abs(k2 - k) * slope_unit
                    + emission(i, pos[b2])
                )
                key = (b2, k2)
                if c2 < nxt.get(key, math.inf):
                    nxt[key] = c2
                    ptr[key] = (b, k)
        cost = nxt
        ptrs.append(ptr)

    state = min(cost, key=cost.get)
    path_bins = [state]
    for ptr in reversed(ptrs):
        state = ptr[state]
        path_bins.append(state)
    path_bins.reverse()

    # Keypoints only where the slope changes (plus both endpoints) — the
    # renderer interpolates linearly in between, losslessly.
    out: List[Tuple[float, float]] = [(times[0], pos[path_bins[0][0]])]
    for i in range(1, n - 1):
        if path_bins[i][1] != path_bins[i + 1][1]:
            out.append((times[i], pos[path_bins[i][0]]))
    out.append((times[-1], pos[path_bins[-1][0]]))
    return out

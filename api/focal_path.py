"""Focal-point smoothing for smart video reframing.

Pure math — no FFmpeg, no I/O. Takes raw focal points from Gemini and
produces a smooth pan path with velocity limiting and deduplication.
"""

import bisect
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cubic Hermite interpolation (Catmull-Rom)
# ---------------------------------------------------------------------------


def _cubic_hermite(t: float, p0: float, m0: float, p1: float, m1: float) -> float:
    """Cubic Hermite interpolation between two points."""
    t2 = t * t
    t3 = t2 * t
    return (
        (2 * t3 - 3 * t2 + 1) * p0
        + (t3 - 2 * t2 + t) * m0
        + (-2 * t3 + 3 * t2) * p1
        + (t3 - t2) * m1
    )


def _compute_tangents(times: List[float], values: List[float]) -> List[float]:
    """Compute Catmull-Rom tangents for a sequence of points."""
    n = len(values)
    tangents = [0.0] * n
    for i in range(n):
        if i == 0:
            dt = (times[1] - times[0]) if n > 1 else 1.0
            tangents[i] = (values[1] - values[0]) / dt if n > 1 and dt > 0 else 0.0
        elif i == n - 1:
            dt = times[i] - times[i - 1]
            tangents[i] = (values[i] - values[i - 1]) / dt if dt > 0 else 0.0
        else:
            dt = times[i + 1] - times[i - 1]
            tangents[i] = (values[i + 1] - values[i - 1]) / dt if dt > 0 else 0.0
    return tangents


def _interpolate_one(
    t: float,
    times: List[float],
    values: List[float],
    tangents: List[float],
) -> float:
    """Interpolate a single value at time t."""
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    seg = min(bisect.bisect_right(times, t) - 1, len(times) - 2)
    dt = times[seg + 1] - times[seg]
    if dt == 0:
        return values[seg]
    local_t = (t - times[seg]) / dt
    return _cubic_hermite(
        local_t,
        values[seg],
        tangents[seg] * dt,
        values[seg + 1],
        tangents[seg + 1] * dt,
    )


def _interpolate_series(
    times: List[float],
    values: List[float],
    eval_times: List[float],
) -> List[float]:
    """Interpolate values at eval_times using cubic Hermite splines."""
    if len(times) < 2:
        return [values[0]] * len(eval_times) if values else [0.5] * len(eval_times)
    tangents = _compute_tangents(times, values)
    return [_interpolate_one(t, times, values, tangents) for t in eval_times]


# ---------------------------------------------------------------------------
# Focal path smoothing pipeline
# ---------------------------------------------------------------------------

_CENTER = (0.5, 0.5)


def smooth_focal_path(
    focal_points: List[dict],
    scene_changes: List[dict],
    duration: float,
    fps: float,
    max_velocity: float = 0.15,
    deadzone: float = 0.05,
) -> List[Tuple[float, float, float]]:
    """Smooth focal points into a pan path with keypoints at ~1/sec."""
    if not focal_points:
        return [(0.0, *_CENTER), (duration, *_CENTER)]

    sorted_pts = _prepare_focal_points(focal_points, duration)
    if not sorted_pts:
        return [(0.0, *_CENTER), (duration, *_CENTER)]

    cuts = _build_scene_boundaries(scene_changes, duration)
    segments = _split_by_scenes(sorted_pts, cuts)
    raw = _interpolate_segments(segments)
    deduped = _deduplicate(raw)
    limited = _apply_velocity_limit(deduped, max_velocity, deadzone)
    collapsed = _collapse_static_runs(limited)

    logger.info(
        f"smooth_focal_path: {len(collapsed)} final keypoints for {duration:.1f}s video"
    )
    return collapsed


def _prepare_focal_points(
    focal_points: List[dict],
    duration: float,
) -> List[dict]:
    """Sort by time and clamp to video duration."""
    pts = sorted(focal_points, key=lambda p: p["time_sec"])
    return [p for p in pts if p["time_sec"] <= duration]


def _build_scene_boundaries(
    scene_changes: List[dict],
    duration: float,
) -> List[float]:
    """Build sorted list of scene-cut boundaries including 0 and end."""
    valid = [sc["time_sec"] for sc in scene_changes if sc["time_sec"] <= duration]
    return sorted(set([0.0] + valid + [duration]))


def _split_by_scenes(
    sorted_pts: List[dict],
    cuts: List[float],
) -> List[Tuple[float, float, List[dict]]]:
    """Split focal points into per-scene segments."""
    segments = []
    pt_times = [p["time_sec"] for p in sorted_pts]
    for i in range(len(cuts) - 1):
        start, end = cuts[i], cuts[i + 1]
        lo = bisect.bisect_left(pt_times, start)
        hi = bisect.bisect_right(pt_times, end)
        pts = sorted_pts[lo:hi]
        if not pts:
            mid = (start + end) / 2
            idx = bisect.bisect_left(pt_times, mid)
            candidates = []
            if idx > 0:
                candidates.append(sorted_pts[idx - 1])
            if idx < len(sorted_pts):
                candidates.append(sorted_pts[idx])
            nearest = min(candidates, key=lambda p: abs(p["time_sec"] - mid))
            pts = [{"time_sec": start, "x": nearest["x"], "y": nearest["y"]}]
        segments.append((start, end, pts))
    return segments


def _interpolate_segments(
    segments: List[Tuple[float, float, List[dict]]],
) -> List[Tuple[float, float, float]]:
    """Interpolate each scene segment at ~1s intervals."""
    all_kps = []
    for seg_start, seg_end, seg_pts in segments:
        seg_dur = seg_end - seg_start
        if seg_dur <= 0:
            continue
        eval_times = _build_eval_times(seg_start, seg_end, seg_dur)
        times = [p["time_sec"] for p in seg_pts]
        x_vals = [max(0.0, min(1.0, p["x"])) for p in seg_pts]
        y_vals = [max(0.0, min(1.0, p["y"])) for p in seg_pts]
        interp_x = _interpolate_series(times, x_vals, eval_times)
        interp_y = _interpolate_series(times, y_vals, eval_times)
        for t, x, y in zip(eval_times, interp_x, interp_y):
            all_kps.append((t, max(0.0, min(1.0, x)), max(0.0, min(1.0, y))))
    return all_kps


def _build_eval_times(start: float, end: float, dur: float) -> List[float]:
    """Build evaluation timestamps at ~1s intervals within a segment."""
    step = 1.0 if dur > 2 else max(0.5, dur)
    times = []
    t = start
    while t < end:
        times.append(t)
        t += step
    times.append(end)
    return times


def _deduplicate(
    keypoints: List[Tuple[float, float, float]],
) -> List[Tuple[float, float, float]]:
    """Remove duplicate-time keypoints at segment boundaries."""
    seen = set()
    result = []
    for kp in keypoints:
        t_r = round(kp[0], 3)
        if t_r not in seen:
            seen.add(t_r)
            result.append(kp)
    return result


def _apply_velocity_limit(
    keypoints: List[Tuple[float, float, float]],
    max_velocity: float,
    deadzone: float,
) -> List[Tuple[float, float, float]]:
    """Clamp horizontal pan speed and suppress small movements."""
    if len(keypoints) <= 1:
        return keypoints
    limited = [keypoints[0]]
    for i in range(1, len(keypoints)):
        dt = keypoints[i][0] - limited[-1][0]
        if dt <= 0:
            limited.append(keypoints[i])
            continue
        dx = keypoints[i][1] - limited[-1][1]
        max_dx = max_velocity * dt
        clamped_x = (
            limited[-1][1] + max_dx * (1 if dx > 0 else -1)
            if abs(dx) > max_dx
            else keypoints[i][1]
        )
        if abs(clamped_x - limited[-1][1]) < deadzone:
            clamped_x = limited[-1][1]
        limited.append(
            (keypoints[i][0], max(0.0, min(1.0, clamped_x)), keypoints[i][2])
        )
    return limited


def _collapse_static_runs(
    keypoints: List[Tuple[float, float, float]],
) -> List[Tuple[float, float, float]]:
    """Drop interior keypoints where x isn't changing."""
    if len(keypoints) <= 2:
        return keypoints
    result = [keypoints[0]]
    for i in range(1, len(keypoints) - 1):
        if (
            keypoints[i][1] != keypoints[i - 1][1]
            or keypoints[i][1] != keypoints[i + 1][1]
        ):
            result.append(keypoints[i])
    result.append(keypoints[-1])
    return result

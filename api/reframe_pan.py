"""Pan-path glue — scene-typed velocity profiles and keypoint attachment.

Chooses each segment's pan responsiveness (measured motion → scene type),
solves the crop path via `focal_path.l1_pan_path`, and seeds mid-shot
continuity so re-frames ease instead of jumping. Pure logic, no I/O.
"""

import statistics
from typing import List, Optional, Tuple

from focal_path import l1_pan_path
from reframe_rungs import rung_coverage
from reframe_signals import _segment_persons, _track_x_spread

# Pan smoothing per Gemini scene_type → (max_velocity frac/s, deadzone frac).
# Replaces the old global content_type setting: framing adapts per scene, so an
# action beat and a dialogue beat in the same video pan differently. Deadzones
# are small: a large deadzone freezes the crop at the first (often off-center)
# keypoint and never re-centers — keep just enough to suppress detection jitter.
SCENE_TYPE_PARAMS: dict[str, Tuple[float, float]] = {
    "dialogue": (0.10, 0.02),  # hold steady on speakers
    "close-up": (0.08, 0.02),  # very stable
    "action": (0.50, 0.02),  # track fast motion
    "establishing": (0.10, 0.02),
    "wide": (0.10, 0.02),
    "general": (0.15, 0.02),
}
DEFAULT_SCENE_PARAMS: Tuple[float, float] = (0.15, 0.02)
# With the dense Gemini scene pass retired, scene_type is derived from MEASURED
# motion: a subject whose x-center ranges more than this across a segment is
# "action" (pan fast); otherwise "general". More accurate than a coarse label.
ACTION_SPREAD = 0.25
# If the subject's x barely moves across a segment, center on its median
# position (robust to boundary jitter) instead of a velocity-limited path that
# can lock off-center.
STATIC_SPREAD = 0.10


def _motion_scene_type(d: dict, tf_win, pf_win) -> str:
    """Pan profile from MEASURED subject motion (replaces the Gemini scene_type).

    The chosen subject's x-center range across the segment: a wide range means the
    subject moves a lot → "action" (pan fast); otherwise "general". Falls back to
    the largest person's spread when the crop follows a body, not a face track.
    """
    crop = d["crops"][0]
    tid = crop.get("track_id")
    if tid is not None:
        spread = _track_x_spread(tf_win, tid)
    else:
        xs = [p["x"] for p in _segment_persons(pf_win)]
        spread = (max(xs) - min(xs)) if xs else 0.0
    return "action" if spread > ACTION_SPREAD else "general"


# A mid-shot re-frame eases to its new target over this long, instead of an
# instantaneous crop jump the viewer sees as a glitchy jump cut. Fast enough to
# read as an intentional pan; only applied when there is no real cut to hide it.
PAN_IN_SEC = 0.4


def _seed_start_x(keypoints, prev_x, deadzone):
    """Start a segment's pan at the previous segment's final x, easing to its
    own first target over PAN_IN_SEC. No-op when already (nearly) continuous."""
    t0, x0, y0 = keypoints[0]
    if abs(prev_x - x0) <= deadzone:
        return keypoints
    rest = keypoints[1:]
    ramp_end = t0 + PAN_IN_SEC
    if rest and rest[0][0] <= ramp_end:
        # The next keypoint is already within the ramp — pan straight to it.
        return [(t0, prev_x, y0)] + rest
    return [(t0, prev_x, y0), (ramp_end, x0, y0)] + rest


# Containment window: how far the subject may sit from the crop center before
# the pan optimizer is forced to move, as a fraction of the crop width. 0.3
# keeps the subject inside the middle ~60% of the crop; the floor covers
# full-width rungs (no freedom) and unknown source dims.
PAN_CONTAIN_FRAC = 0.3
PAN_CONTAIN_MIN = 0.03
PAN_CONTAIN_DEFAULT = 0.08


def attach_keypoints(
    segments: List[dict],
    fps: float,
    src_w: Optional[int] = None,
    src_h: Optional[int] = None,
) -> List[dict]:
    """Solve each crop's pan path into keypoints (per-segment, scene-bounded).

    Moving subjects go through `l1_pan_path` (L1 trajectory optimization):
    holds and constant-velocity pans emerge from the objective, jitter inside
    the containment window produces no motion, and speed is capped by the
    segment's scene_type (action pans fast, dialogue holds steady). The window
    scales with the segment's rung when `src_w`/`src_h` are given — a looser
    crop tolerates more subject drift before panning. Keypoints are in absolute
    video time; the renderer rebases them per segment.

    Continuity: segments are solved independently, so two adjacent cells of
    the SAME continuous shot (MAX_SEG_LEN subdivisions, speaker-turn re-cuts)
    can land on different x targets — an instantaneous crop jump with no visual
    cut to hide it. When a segment does not start at a real scene cut
    (`starts_at_cut` from reconcile; absent = assume a cut), its pan is seeded
    from the previous segment's final x and eases to its own target.
    """
    prev_x: Optional[float] = None  # previous segment's final crop x (single-crop)
    for seg in segments:
        start, end = seg["start"], seg["end"]
        max_velocity, deadzone = SCENE_TYPE_PARAMS.get(
            seg.get("scene_type", ""), DEFAULT_SCENE_PARAMS
        )
        inner = seg.get("inner_ar")
        if src_w and src_h and inner:
            cov = rung_coverage(tuple(inner), src_w, src_h)
            contain = max(PAN_CONTAIN_MIN, PAN_CONTAIN_FRAC * cov)
        else:
            contain = PAN_CONTAIN_DEFAULT
        for crop in seg["crops"]:
            pts = crop.get("focal_points") or [
                {"time_sec": start, "x": crop.get("x_target", 0.5), "y": 0.5}
            ]
            xs = [p["x"] for p in pts]
            cy = statistics.median([p.get("y", 0.5) for p in pts])
            # ~Static subject → center on the median (robust to boundary jitter).
            if max(xs) - min(xs) <= STATIC_SPREAD:
                cx = statistics.median(xs)
                crop["keypoints"] = [(start, cx, cy), (end, cx, cy)]
                continue
            path = l1_pan_path(pts, start, end, contain, max_velocity)
            crop["keypoints"] = [(t, x, cy) for (t, x) in path]
        single = seg.get("layout") != "split" and len(seg["crops"]) == 1
        if single and prev_x is not None and not seg.get("starts_at_cut", True):
            crop = seg["crops"][0]
            crop["keypoints"] = _seed_start_x(crop["keypoints"], prev_x, deadzone)
        # Split panels have no single continuity target; re-frame hard after one.
        prev_x = seg["crops"][0]["keypoints"][-1][1] if single else None
    return segments

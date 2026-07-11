"""Baked-in letterbox/pillarbox detection — the source's ACTIVE picture area.

Cinema-scope trailers (and phone-recorded TV screens) ship the picture inside a
larger padded container: a 2.39:1 movie inside a 16:9 file wastes ~26% of every
frame on black bars. A 9:16 crop of such a source keeps those bars, so the
rendered output fills only ~74% of the canvas even when the crop itself is
perfect — and every geometric decision (rung coverage, face-width fractions,
letterbox math) silently reasons about pixels that aren't picture.

The fix is upstream of everything: detect the active rect once per job and run
the WHOLE pipeline in active-picture coordinates — detection scans slice frames
before inference (fractions come out active-normalized for free), planning/eval
receive the active dimensions as src_w/src_h, and the renderer prepends one
`crop=` to each filter chain so the pan math needs no remapping.

A bar row must be dark in ≥ (1 - OUTLIER_FRAC) of sampled frames — not ALL of
them, because the trailer format itself mixes aspects: the Spider-Man reference
is pure scope for 95% of its runtime and full-bleed for the end slate. Those
minority full-bleed samples come back as ``outlier_times``; the worker maps
them to their shots and the renderer drops the trim for just those segments
(exact for letterbox bars: a full-width crop never changes x fractions).
Within a frame the rule stays conservative — a single bright pixel in a row
(baked subtitles, billing block, logo in the bar) keeps that row.
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover - environments without OpenCV
    cv2 = None

logger = logging.getLogger(__name__)

# 8-bit luma ceiling for "this pixel is padding". BT.601 video black is 16;
# the headroom above it absorbs compression noise at bar edges.
BAR_LUMA = 24
# Don't bother trimming hairline bars — coordinate churn without visible gain.
MIN_BAR_FRAC = 0.02
# A "bar" deeper than a third of the frame is content (night scene, fade), not
# padding — reject that side entirely rather than trim into the picture.
MAX_BAR_FRAC = 0.35
# Sanity floor: never keep less than half the frame area.
MIN_ACTIVE_FRAC = 0.5
# Fraction of sampled frames allowed to violate the bar config (full-bleed end
# slates, logo cards). More disagreement than this = a genuinely mixed-format
# source → no trim at all.
OUTLIER_FRAC = 0.15
N_SAMPLES = 24


def active_area_from_frames(frames) -> Optional[dict]:
    """Active picture rect from a sequence of same-sized frames (BGR or gray).

    Returns fractional ``{"x0", "y0", "x1", "y1", "outliers": [idx...]}`` or
    ``None`` when the frames are (effectively) all picture. ``outliers`` lists
    the indices of frames that violate the bar config (e.g. a full-bleed end
    slate) — callers map them back to shots. Pure numpy — unit-testable
    without video I/O.
    """
    row_profiles, col_profiles = [], []
    for frame in frames:
        gray = frame if frame.ndim == 2 else frame.max(axis=2)
        row_profiles.append(gray.max(axis=1))
        col_profiles.append(gray.max(axis=0))
    n = len(row_profiles)
    if n == 0:
        return None
    rows = np.stack(row_profiles) < BAR_LUMA  # (n, h) — per-frame bar rows
    cols = np.stack(col_profiles) < BAR_LUMA
    h, w = rows.shape[1], cols.shape[1]
    need = 1.0 - OUTLIER_FRAC

    def bar_depth(dark_frac: np.ndarray, reverse: bool) -> int:
        dark = dark_frac >= need
        if reverse:
            dark = dark[::-1]
        depth = int(np.argmin(dark)) if not dark.all() else len(dark)
        frac = depth / len(dark)
        if frac < MIN_BAR_FRAC or frac > MAX_BAR_FRAC:
            return 0
        return depth

    top = bar_depth(rows.mean(axis=0), reverse=False)
    bottom = bar_depth(rows.mean(axis=0), reverse=True)
    left = bar_depth(cols.mean(axis=0), reverse=False)
    right = bar_depth(cols.mean(axis=0), reverse=True)
    if not any((top, bottom, left, right)):
        return None

    x0, x1 = left / w, (w - right) / w
    y0, y1 = top / h, (h - bottom) / h
    if (x1 - x0) * (y1 - y0) < MIN_ACTIVE_FRAC:
        return None

    # A frame is an outlier when its own bar region carries picture (any
    # non-dark row/col inside the trim) — the full-bleed shots of a mixed cut.
    outliers = [
        i
        for i in range(n)
        if not (
            rows[i, :top].all()
            and (bottom == 0 or rows[i, h - bottom :].all())
            and cols[i, :left].all()
            and (right == 0 or cols[i, w - right :].all())
        )
    ]
    if len(outliers) > OUTLIER_FRAC * n:  # profile said trim, frames disagree
        return None
    return {
        "x0": round(x0, 4),
        "y0": round(y0, 4),
        "x1": round(x1, 4),
        "y1": round(y1, 4),
        "outliers": outliers,
    }


def detect_active_area(video_path: str, samples: int = N_SAMPLES) -> Optional[dict]:
    """Detect the active picture rect of a video (fractional, or ``None``).

    Samples evenly across the middle 94% of the timeline (skipping fade-in /
    fade-out frames that are legitimately black). ``outliers`` indices become
    ``outlier_times`` (seconds). Best-effort: any decode problem returns
    ``None`` (= full frame, today's behavior).
    """
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"active_area: cannot open {video_path}")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    times: List[float] = []

    def _frames():
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total <= 0:
            return
        for i in np.linspace(0.03 * total, 0.97 * total, num=samples):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, frame = cap.read()
            if ok and frame is not None:
                times.append(int(i) / fps)
                yield frame

    try:
        area = active_area_from_frames(_frames())
        if area is not None:
            area["outlier_times"] = [
                round(times[i], 2) for i in area.pop("outliers", []) if i < len(times)
            ]
        return area
    except Exception as e:  # never fail the job over bar detection
        logger.warning(f"active_area: detection failed ({e})")
        return None
    finally:
        cap.release()


def outlier_shot_ranges(
    area: Optional[dict], cuts: List[float], duration: float
) -> List[Tuple[float, float]]:
    """The shot intervals containing the full-bleed outlier samples.

    Segments overlapping these ranges must render WITHOUT the source trim
    (their pixels genuinely extend into the bar region). Exact for letterbox
    bars: the full-width crop means x fractions are identical either way.
    """
    if not area or not area.get("outlier_times"):
        return []
    bounds = [0.0] + sorted(cuts) + [duration]
    ranges = []
    for t in area["outlier_times"]:
        for s, e in zip(bounds, bounds[1:]):
            if s <= t < e:
                if not ranges or ranges[-1] != (s, e):
                    ranges.append((s, e))
                break
    return ranges


def rect_px(area: Optional[dict], w: int, h: int) -> Tuple[int, int, int, int]:
    """Fractional rect → even-aligned pixel rect ``(x, y, w, h)`` inside w×h."""
    if not area:
        return 0, 0, w, h
    x = _even(round(area["x0"] * w))
    y = _even(round(area["y0"] * h))
    ww = min(_even(round((area["x1"] - area["x0"]) * w)), w - x)
    hh = min(_even(round((area["y1"] - area["y0"]) * h)), h - y)
    if ww <= 0 or hh <= 0:
        return 0, 0, w, h
    return x, y, ww, hh


def crop_prefilter(px_rect: Tuple[int, int, int, int], w: int, h: int) -> str:
    """FFmpeg `crop=` prefix trimming the source to its active rect ("" if full)."""
    x, y, ww, hh = px_rect
    if (x, y, ww, hh) == (0, 0, w, h):
        return ""
    return f"crop={ww}:{hh}:{x}:{y},"


def slice_frame(frame, area: Optional[dict]):
    """Trim a decoded frame to the active rect (no-op when area is None)."""
    if not area:
        return frame
    h, w = frame.shape[:2]
    x, y, ww, hh = rect_px(area, w, h)
    return frame[y : y + hh, x : x + ww]


def _even(n: int) -> int:
    return int(n) - (int(n) % 2)


def summarize(area: Optional[dict]) -> Optional[dict]:
    """Observability blob for reframe_summary / eval perception ("what got trimmed")."""
    if not area:
        return None
    kind = "letterbox" if (area["y1"] - area["y0"]) < 1.0 else "pillarbox"
    return {
        "x0": area["x0"],
        "y0": area["y0"],
        "x1": area["x1"],
        "y1": area["y1"],
        "kind": kind,
        "picture_frac": round((area["x1"] - area["x0"]) * (area["y1"] - area["y0"]), 3),
        "full_bleed_samples": len(area.get("outlier_times", [])),
    }

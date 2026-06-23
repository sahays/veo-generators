"""Wide-text region detection — reframe v2 Phase 2 precision layer.

Gemini flags *that* a shot carries full-width text (title card, lower-third,
logo, slide); this module measures *how wide* that text actually is, frame-
accurately, so the planner letterboxes to the real extent instead of trusting
Gemini's coarse coverage number. This is the "CPU locates what Gemini named"
half of the precision stack (the riskiest accuracy gap in the v2 plan).

Deliberately classical OpenCV morphology — no model download, no new dependency
(opencv is already pinned for MediaPipe), low latency, no cold start. It is
best-effort: degrades to "no text" if cv2 is unavailable or a frame can't be
read, so the pipeline simply falls back to Gemini's flag.

The exported signal is a horizontal *coverage* fraction in [0, 1]: the width of
the widest persistent text line as a fraction of source width. The planner
reconciles it with Gemini's semantic flag via
``reframe_plan.reconcile_text_coverage``.
"""

import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
except Exception:  # pragma: no cover — cv2 is always present in the worker image
    cv2 = None
    np = None

# Geometry filters (fractions of frame dims unless noted). A "text line" is a row
# of glyph clusters; these reject specks, full-frame blobs, and tall graphics.
_MIN_GLYPH_H = 0.015  # a glyph cluster at least this tall — drop sub-pixel speckle
_MAX_GLYPH_H = 0.30  # ...and at most this tall — drop big graphics / frame contours
_MIN_GLYPH_W = 0.01  # ...and at least this wide — drop dot-sized noise
_MIN_LINE_W = 0.20  # only *wide* text lines drive letterbox decisions
_MIN_AR = 4.0  # text lines are wide: line width/height ratio floor
_MIN_LINE_DENSITY = 0.25  # glyphs must fill ≥ this fraction of the line's span —
#                           rejects two specks at opposite edges unioning to "wide"
# Stroke density inside a glyph box (on the binarized edge map). Real text is a
# sparse field of strokes; an empty box is ~0 and a solid filled bar is ~1.
_MIN_FILL = 0.08
_MAX_FILL = 0.70
# A frame counts toward "has wide text" once its widest line reaches this.
_WIDE_COVERAGE = 0.20


def _group_lines(boxes):
    """Group glyph boxes (x0, y0, x1, y1) into text lines by vertical proximity.

    Boxes on the same baseline share a vertical band; each line accumulates a
    union extent plus the summed glyph width (for the density check).
    """
    lines: List[List[float]] = []  # [x0, y0, x1, y1, summed_glyph_width]
    for bx0, by0, bx1, by1 in sorted(boxes, key=lambda b: b[1]):
        cy = (by0 + by1) / 2
        gh = by1 - by0
        for ln in lines:
            lcy = (ln[1] + ln[3]) / 2
            if abs(cy - lcy) <= 0.6 * max(gh, ln[3] - ln[1]):
                ln[0], ln[1] = min(ln[0], bx0), min(ln[1], by0)
                ln[2], ln[3] = max(ln[2], bx1), max(ln[3], by1)
                ln[4] += bx1 - bx0
                break
        else:
            lines.append([bx0, by0, bx1, by1, bx1 - bx0])
    return lines


def detect_text_coverage(frame) -> Tuple[float, Tuple[float, float]]:
    """Widest text-line coverage in a single BGR frame.

    Returns ``(coverage_frac, (x0_frac, x1_frac))`` for the widest qualifying
    text line — coverage is that line's union width / frame width — or
    ``(0.0, (0.0, 0.0))`` when no text-like region is found.
    """
    if cv2 is None or frame is None or getattr(frame, "size", 0) == 0:
        return 0.0, (0.0, 0.0)
    h, w = frame.shape[:2]
    if h < 32 or w < 32:
        return 0.0, (0.0, 0.0)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Morphological gradient highlights glyph strokes (edges) regardless of text
    # colour; Otsu binarizes it adaptively to the frame's contrast.
    grad = cv2.morphologyEx(
        gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    )
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # Close with a short, wide kernel to fuse strokes within a glyph/word (not
    # across whole lines — line grouping below handles word gaps geometrically).
    kx = max(5, int(w * 0.012))
    connected = cv2.morphologyEx(
        bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 1))
    )
    contours, _ = cv2.findContours(
        connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    glyphs = []
    for c in contours:
        bx, by, bw_, bh_ = cv2.boundingRect(c)
        if bh_ < _MIN_GLYPH_H * h or bh_ > _MAX_GLYPH_H * h:
            continue
        if bw_ < _MIN_GLYPH_W * w:
            continue
        region = bw[by : by + bh_, bx : bx + bw_]
        fill = float((region > 0).mean()) if region.size else 0.0
        if fill < _MIN_FILL or fill > _MAX_FILL:
            continue
        glyphs.append((bx, by, bx + bw_, by + bh_))

    best_cov = 0.0
    best_span = (0.0, 0.0)
    for x0, y0, x1, y1, sum_w in _group_lines(glyphs):
        union_w = x1 - x0
        if union_w < _MIN_LINE_W * w:
            continue
        if union_w / max(1, y1 - y0) < _MIN_AR:
            continue
        if sum_w / union_w < _MIN_LINE_DENSITY:
            continue
        cov = union_w / w
        if cov > best_cov:
            best_cov = cov
            best_span = (x0 / w, x1 / w)
    return best_cov, best_span


def scan_video_text(video_path: str, sample_fps: float = 0.5) -> List[dict]:
    """Sample the video and measure wide-text coverage per frame.

    Returns ``[{"time_sec", "coverage", "span": (x0, x1)}]``. On-screen text
    persists across seconds, so a sparse sample is enough; this runs its own
    decode pass (an independent Stage-1 precision pass) and degrades to ``[]``
    if the video can't be opened or cv2 is unavailable.
    """
    if cv2 is None:
        logger.warning("text_detect: cv2 unavailable — text detection disabled")
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"text_detect: failed to open {video_path}")
        return []

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, int(video_fps / sample_fps))
    out: List[dict] = []
    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % step == 0:
                cov, span = detect_text_coverage(frame)
                out.append({"time_sec": idx / video_fps, "coverage": cov, "span": span})
            idx += 1
    finally:
        cap.release()

    wide = sum(1 for f in out if f["coverage"] >= _WIDE_COVERAGE)
    logger.info(f"text_detect: {len(out)} frames, {wide} with wide text")
    return out

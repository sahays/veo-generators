"""Wide-text region detection — reframe v2 Phase 2 precision layer.

Gemini flags *that* a shot carries full-width text (title card, lower-third,
logo, slide); this module measures *how wide* that text actually is, frame-
accurately, so the planner letterboxes to the real extent instead of trusting
Gemini's coarse coverage number. This is the "CPU locates what Gemini named"
half of the precision stack (the riskiest accuracy gap in the v2 plan).

Deliberately classical OpenCV morphology — no model download, no new dependency
(opencv is already pinned for MediaPipe), low latency, no cold start. It is
best-effort: degrades to "no text" if cv2 is unavailable or a frame can't be
read.

The exported signal is a horizontal *coverage* fraction in [0, 1]: the width of
the widest persistent text line as a fraction of source width. When a persistent
wide band would be clipped by the subject's tight crop, the planner escalates it
to the decision model (``reframe_plan._maybe_text_escalation``) rather than
self-letterboxing — the morphology detector can't tell a real caption from a busy
background.
"""

import logging
from typing import List, Optional, Tuple

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


def detect_text_lines(frame) -> List[Tuple[float, float, float, float]]:
    """Every qualifying text line in a single BGR frame.

    Returns normalized ``(x0, y0, x1, y1)`` boxes (fractions of frame dims), one
    per line that passes the per-line text filters — the per-region geometry the
    planner's conflict test and the persistent-region classifier consume. Empty
    list when nothing text-like is found.
    """
    if cv2 is None or frame is None or getattr(frame, "size", 0) == 0:
        return []
    h, w = frame.shape[:2]
    if h < 32 or w < 32:
        return []

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

    lines: List[Tuple[float, float, float, float]] = []
    for x0, y0, x1, y1, sum_w in _group_lines(glyphs):
        union_w = x1 - x0
        if union_w < _MIN_LINE_W * w:
            continue
        if union_w / max(1, y1 - y0) < _MIN_AR:
            continue
        if sum_w / union_w < _MIN_LINE_DENSITY:
            continue
        lines.append((x0 / w, y0 / h, x1 / w, y1 / h))
    return lines


def detect_text_coverage(frame) -> Tuple[float, Tuple[float, float]]:
    """Horizontal reach of the on-screen text in a single BGR frame.

    Returns ``(coverage_frac, (x0_frac, x1_frac))`` where the span is the UNION
    reach of every qualifying text line (leftmost start → rightmost end) and
    coverage is that reach / frame width — or ``(0.0, (0.0, 0.0))`` when no
    text-like region is found.

    Clip risk is a per-side *reach* property, not a single-line one: scattered
    callouts on different baselines (a product ad's labels) never form one wide
    line, but their union reaches both edges, so a tight centre crop would clip
    them. NOTE: the union also inflates a narrow corner bug + a real caption
    into one wide band — per-region consumers should prefer
    ``detect_text_lines`` / ``persistent_text_regions``.
    """
    lines = detect_text_lines(frame)
    if not lines:
        return 0.0, (0.0, 0.0)
    min_x0 = min(ln[0] for ln in lines)
    max_x1 = max(ln[2] for ln in lines)
    return max_x1 - min_x0, (min_x0, max_x1)


def scan_video_text(
    video_path: str, sample_fps: float = 2.0, active_area: Optional[dict] = None
) -> List[dict]:
    """Sample the video and measure wide-text coverage per frame.

    Returns ``[{"time_sec", "coverage", "span": (x0, x1)}]``. Runs its own decode
    pass (an independent Stage-1 precision pass) and degrades to ``[]`` if the
    video can't be opened or cv2 is unavailable.

    ``sample_fps`` defaults to 2.0 so even a short (~1-1.5s) shot yields the ≥2
    samples the per-segment persistence gate (``_segment_text_band``) needs to
    tell persistent text from a one-frame flash — at the old 0.5fps a sub-2s
    caption shot could fall below that and be silently dropped. Decode cost is
    unchanged (every frame is read regardless); only the per-sample morphology
    runs more often, which is cheap.

    ``active_area`` trims baked-in bars first (see scan_video_detections), so
    line boxes are normalized to the real picture.
    """
    if cv2 is None:
        logger.warning("text_detect: cv2 unavailable — text detection disabled")
        return []
    from reframe_active_area import slice_frame

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
                lines = detect_text_lines(slice_frame(frame, active_area))
                if lines:
                    x0 = min(ln[0] for ln in lines)
                    x1 = max(ln[2] for ln in lines)
                    cov, span = x1 - x0, (x0, x1)
                else:
                    cov, span = 0.0, (0.0, 0.0)
                out.append(
                    {
                        "time_sec": idx / video_fps,
                        "coverage": cov,
                        "span": span,
                        "lines": [[round(v, 4) for v in ln] for ln in lines],
                    }
                )
            idx += 1
    finally:
        cap.release()

    wide = sum(1 for f in out if f["coverage"] >= _WIDE_COVERAGE)
    logger.info(f"text_detect: {len(out)} frames, {wide} with wide text")
    return out


# ---------------------------------------------------------------------------
# Cross-frame text regions (Phase 3)
# ---------------------------------------------------------------------------
# The per-frame union band inflates a corner watermark + a real caption into one
# frame-wide band — the root of chronic over-letterboxing. Clustering lines
# ACROSS frames yields stable regions the planner can reason about one by one:
# a channel bug present through most of the video is never letterbox-driving; a
# shot-local lower-third is a real candidate the crop must not clip.
_REGION_IOU = 0.30  # a line joins the region it overlaps this much
_BUG_VIDEO_FRAC = 0.60  # present in ≥ this fraction of ALL frames…
_BUG_MAX_AREA = 0.02  # …no bigger than this fraction of the frame…
_BUG_CORNER = 0.30  # …and centered within this of a frame corner = watermark/bug


def _box_iou(a, b) -> float:
    iw = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    ih = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = iw * ih
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def persistent_text_regions(text_frames: List[dict]):
    """Cluster per-frame text lines into video-level regions and classify them.

    Returns a list of ``{"box": [x0, y0, x1, y1], "times": [...],
    "video_frac": float, "kind": "bug" | "candidate"}`` — or ``None`` when the
    frames carry no per-line data (legacy captures), so callers can fall back to
    the union-band path instead of concluding "no text".

    ``bug``: small, corner-anchored, and present through most of the video — a
    watermark/channel bug that must never drive a letterbox decision.
    """
    if not any("lines" in f for f in text_frames or []):
        return None
    total = len(text_frames) or 1
    regions: List[dict] = []  # {box (running mean), times, n}
    for f in text_frames:
        for ln in f.get("lines") or []:
            for r in regions:
                if _box_iou(ln, r["box"]) >= _REGION_IOU:
                    n = r["n"]
                    r["box"] = [(r["box"][i] * n + ln[i]) / (n + 1) for i in range(4)]
                    r["n"] = n + 1
                    if not r["times"] or r["times"][-1] != f["time_sec"]:
                        r["times"].append(f["time_sec"])
                    break
            else:
                regions.append({"box": list(ln), "times": [f["time_sec"]], "n": 1})

    out = []
    for r in regions:
        x0, y0, x1, y1 = r["box"]
        video_frac = len(r["times"]) / total
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        corner = min(cx, 1 - cx) < _BUG_CORNER and min(cy, 1 - cy) < _BUG_CORNER
        kind = (
            "bug"
            if video_frac >= _BUG_VIDEO_FRAC and area <= _BUG_MAX_AREA and corner
            else "candidate"
        )
        out.append(
            {
                "box": [round(v, 4) for v in r["box"]],
                "times": r["times"],
                "video_frac": round(video_frac, 3),
                "kind": kind,
            }
        )
    return out

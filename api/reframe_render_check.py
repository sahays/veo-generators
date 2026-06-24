"""Sampled render-output check — the one eval stage that looks at OUTPUT pixels.

The reference-free eval (`reframe_eval`) scores the plan's *geometry* against
detections; it never decodes the rendered video, so it cannot catch FFmpeg/encode
defects — a black/garbled frame, a wrong crop offset, a broken vstack panel. This
stage closes that gap: it decodes a handful of frames of the finished canvas, runs
face detection on them, and confirms the framed subject actually landed where the
plan predicted.

cv2/ffmpeg/MediaPipe-bound, so it lives outside the pure `reframe_eval` module and
runs in the worker (the Docker image has libGL + ffmpeg; the host venv does not).
Best-effort: returns ``{}`` if the output can't be opened or models are
unavailable — it never fails the job. The placement prediction comes from the
plan and the *measurement* from the decoded output, so the two stay independent.
"""

import logging
from typing import List

from reframe_eval import _flag, _pct, _r, _rollup
from reframe_filters import crop_geometry, crop_left_px_at

logger = logging.getLogger(__name__)

try:
    import cv2
except Exception:  # pragma: no cover — cv2 is always present in the worker image
    cv2 = None

BLANK_STD = 6.0  # grayscale stdev below this → an effectively blank / black frame
# Two-tier position check (deliberately separate concerns):
#   • POS_TOL gates the BINARY "is the framed face even present near where we put
#     it?" count (face_present_rate). It is intentionally generous — a face a bit
#     off but clearly in-frame still counts as "present", so detector jitter / a
#     loose pan doesn't read as a missing subject.
#   • PLACEMENT QUALITY is graded separately by position_error_p90 against the
#     tighter POSITION=(0.15,0.30) thresholds. So a face that lands at 0.16 counts
#     as present (≤0.18) yet still trips the position warn — present ≠ well-placed.
# Tighten POS_TOL only if you want presence itself to demand tight placement.
POS_TOL = 0.18  # |detected − predicted| out_x within this counts as present
MAX_SAMPLES = 12  # cap decoded frames — this is a sampled tripwire, not a full scan

# Flag thresholds (warn, fail).
NONBLANK = (0.95, 0.80)  # higher better — black output is the worst failure
FACE_PRESENT = (0.70, 0.40)  # higher better — framed subject present in output
POSITION = (0.15, 0.30)  # lower better — output face near predicted x
PANEL_FILL = (0.80, 0.50)  # higher better — both split panels show a person


def _kp_x(kps, t: float) -> float:
    """Fractional subject-center x the crop was built around, at time t."""
    if not kps:
        return 0.5
    if t <= kps[0][0]:
        return kps[0][1]
    if t >= kps[-1][0]:
        return kps[-1][1]
    for (t0, x0, _), (t1, x1, _) in zip(kps, kps[1:]):
        if t < t1:
            return x0 if t1 == t0 else x0 + (x1 - x0) * (t - t0) / (t1 - t0)
    return kps[-1][1]


def _predicted_out_x(crop, src_w, crop_w, max_x, t) -> float:
    """Where the framed subject should appear horizontally in the OUTPUT frame.

    The crop is centered on the subject's pan x; mapping that source x through the
    (possibly clamped) crop window gives its position across the output width —
    0.5 when unclamped, shifted toward an edge when the pan hit a frame boundary.
    """
    if crop_w <= 0:
        return 0.5
    kps = crop.get("keypoints") or []
    xk = _kp_x(kps, t)
    left = crop_left_px_at(kps, src_w, crop_w, max_x, t)
    return (xk * src_w - left) / crop_w


def _is_blank(frame) -> bool:
    """True if the frame is effectively flat (black / solid) — a render failure."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(gray.std()) < BLANK_STD


def _sample_indices(n: int, k: int) -> List[int]:
    """Up to k evenly spaced segment indices in [0, n)."""
    if n <= 0 or k <= 0:
        return []
    if n <= k:
        return list(range(n))
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


def _summarize(
    sampled,
    nonblank,
    face_expected,
    face_present,
    pos_errors,
    panel_hits,
    panel_total,
    worst,
) -> dict:
    """Aggregate per-sample counters into the report block (pure)."""
    if not sampled:
        return {}
    nonblank_rate = nonblank / sampled
    face_present_rate = (face_present / face_expected) if face_expected else None
    pos_p90 = _pct(pos_errors, 0.9) if pos_errors else None
    panel_fill_rate = (panel_hits / panel_total) if panel_total else None
    flag = _rollup(
        _flag(nonblank_rate, *NONBLANK, higher_is_better=True),
        _flag(face_present_rate, *FACE_PRESENT, higher_is_better=True),
        _flag(pos_p90, *POSITION, higher_is_better=False),
        _flag(panel_fill_rate, *PANEL_FILL, higher_is_better=True),
    )
    return {
        "frames_sampled": sampled,
        "nonblank_rate": round(nonblank_rate, 3),
        "face_present_rate": _r(face_present_rate),
        "position_error_p90": _r(pos_p90),
        "split_panel_fill_rate": _r(panel_fill_rate),
        "worst": [{"t": round(t, 2), "detail": d} for t, d in worst[:5]],
        "flag": flag,
    }


def check_render(
    out_path: str,
    segments: List[dict],
    src_w: int,
    src_h: int,
    out_w: int = 1080,
    out_h: int = 1920,
    max_samples: int = MAX_SAMPLES,
) -> dict:
    """Decode sampled output frames and score them against the plan's predictions.

    Returns a report block (see `_summarize`) or ``{}`` if unavailable.
    """
    if cv2 is None or not segments:
        return {}
    cap = cv2.VideoCapture(out_path)
    if not cap.isOpened():
        logger.warning(f"render_check: cannot open {out_path}")
        return {}

    from mediapipe_detection import detect_faces

    sampled = nonblank = 0
    face_expected = face_present = 0
    panel_hits = panel_total = 0
    pos_errors: List[float] = []
    worst: List[tuple] = []
    try:
        for i in _sample_indices(len(segments), max_samples):
            seg = segments[i]
            t = (seg["start"] + seg["end"]) / 2.0
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            sampled += 1
            if _is_blank(frame):
                worst.append((t, "blank / near-black output frame"))
                continue
            nonblank += 1
            fh, fw = frame.shape[:2]
            faces = detect_faces(frame, fw, fh)  # fractional in OUTPUT space
            crops = seg.get("crops") or []

            if seg.get("layout") == "split" and len(crops) == 2:
                # Both stacked panels must show a person (top half + bottom half).
                top = any(f["y"] < 0.5 for f in faces)
                bot = any(f["y"] >= 0.5 for f in faces)
                panel_total += 2
                panel_hits += int(top) + int(bot)
                if not (top and bot):
                    worst.append((t, f"split panel empty (top={top}, bot={bot})"))
                continue

            crop = crops[0] if crops else {}
            if crop.get("track_id") is None or crop.get("source") not in (
                "face",
                "speaker",
            ):
                continue  # body / center / text crop → no single face to expect
            face_expected += 1
            if not faces:
                worst.append((t, "framed face absent in output"))
                continue
            crop_w, _fg, max_x = crop_geometry(tuple(seg["inner_ar"]), src_w, src_h)
            pred = _predicted_out_x(crop, src_w, crop_w, max_x, t)
            err = min(abs(f["x"] - pred) for f in faces)
            pos_errors.append(err)
            if err <= POS_TOL:
                face_present += 1
            else:
                worst.append(
                    (t, f"framed face at out_x off by {err:.2f} (pred {pred:.2f})")
                )
    finally:
        cap.release()

    return _summarize(
        sampled,
        nonblank,
        face_expected,
        face_present,
        pos_errors,
        panel_hits,
        panel_total,
        worst,
    )

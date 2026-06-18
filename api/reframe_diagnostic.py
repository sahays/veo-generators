"""Diagnostic-mode renderer for smart reframing.

Draws what the detection models *see* — MediaPipe face-track boxes (red) and
per-scene Gemini labels — onto the full, uncropped 16:9 frame, then letterboxes
it into the 9:16 mobile canvas over a blurred background. A visualization/debug
feature (per-job toggle), not part of the crop pipeline.

Optionally overlays the chosen crop window per segment (green) when a reframe
plan is supplied, so you can see exactly what the v2 pipeline would keep vs.
discard.
"""

import bisect
import logging
import tempfile
from typing import List, Optional, Tuple

import cv2

from ffmpeg_runner import run_ffmpeg

logger = logging.getLogger(__name__)

# OpenCV uses BGR.
_RED = (0, 0, 255)  # face boxes
_ORANGE = (0, 140, 255)  # person (body) boxes
_GREEN = (0, 255, 0)  # chosen crop window
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)

CANVAS_W, CANVAS_H = 1080, 1920


# ---------------------------------------------------------------------------
# Label + lookup helpers
# ---------------------------------------------------------------------------


def track_label_map(tracked_frames: List[dict]) -> dict:
    """Map track_id → label (A, B, C…) ranked by visibility (most frames first).

    Matches the labelling in workers/_reframe_helpers.format_track_summary so the
    boxes drawn here line up with what Gemini is told.
    """
    counts: dict = {}
    for frame in tracked_frames:
        for t in frame.get("tracks", []):
            counts[t["track_id"]] = counts.get(t["track_id"], 0) + 1
    ranked = sorted(counts, key=lambda tid: -counts[tid])
    return {
        tid: (chr(ord("A") + i) if i < 26 else str(tid)) for i, tid in enumerate(ranked)
    }


def _nearest_tracks(tracked_frames: List[dict], times: List[float], t: float) -> list:
    """Tracks from the most recent sampled frame at or before time t (held)."""
    if not tracked_frames:
        return []
    i = bisect.bisect_right(times, t) - 1
    i = max(0, min(i, len(tracked_frames) - 1))
    return tracked_frames[i].get("tracks", [])


def _scene_at(scenes: List[dict], starts: List[float], t: float) -> Optional[dict]:
    if not scenes:
        return None
    i = bisect.bisect_right(starts, t) - 1
    if i < 0:
        return None
    return scenes[i]


def _interp_x(keypoints: List[Tuple[float, float, float]], t: float) -> float:
    """Linear interpolation of the fractional x center at time t."""
    if not keypoints:
        return 0.5
    if t <= keypoints[0][0]:
        return keypoints[0][1]
    if t >= keypoints[-1][0]:
        return keypoints[-1][1]
    times = [kp[0] for kp in keypoints]
    i = min(bisect.bisect_right(times, t) - 1, len(keypoints) - 2)
    t0, x0, _ = keypoints[i]
    t1, x1, _ = keypoints[i + 1]
    frac = (t - t0) / (t1 - t0) if t1 != t0 else 0.0
    return x0 + (x1 - x0) * frac


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------


def _draw_box(frame, x0, y0, x1, y1, color, thickness, label=None, scale=0.6):
    """Draw a rectangle with an optional label chip above its top-left corner."""
    h, w = frame.shape[:2]
    x0 = max(0, min(w - 1, int(x0)))
    x1 = max(0, min(w - 1, int(x1)))
    y0 = max(0, min(h - 1, int(y0)))
    y1 = max(0, min(h - 1, int(y1)))
    cv2.rectangle(frame, (x0, y0), (x1, y1), color, thickness)
    if label:
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        ly = max(th + 4, y0)
        cv2.rectangle(frame, (x0, ly - th - 4), (x0 + tw + 4, ly), color, -1)
        cv2.putText(
            frame,
            label,
            (x0 + 2, ly - 3),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            _BLACK,
            1,
            cv2.LINE_AA,
        )


def _draw_caption(frame, lines, scale):
    """Draw stacked caption banners (scene label, then the decision trigger)."""
    w = frame.shape[1]
    (_tw, th), _ = cv2.getTextSize("Ag", cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    row = th + 12
    cv2.rectangle(frame, (0, 0), (w, row * len(lines) + 4), _BLACK, -1)
    for i, text in enumerate(lines):
        cv2.putText(
            frame, text, (10, row * i + th + 6),
            cv2.FONT_HERSHEY_SIMPLEX, scale, _WHITE, 2, cv2.LINE_AA,
        )


def _annotate_frame(frame, t, ctx):
    """Draw all overlays onto a single native-resolution BGR frame."""
    h, w = frame.shape[:2]
    thick = max(2, w // 500)
    scale = max(0.5, w / 1600)

    # Orange: person/body detections (drawn first, under faces). Catches subjects
    # with no visible frontal face (distant, profile, low-light, walking away).
    if ctx["persons"]:
        i = bisect.bisect_right(ctx["person_times"], t) - 1
        if 0 <= i < len(ctx["persons"]):
            for p in ctx["persons"][i].get("persons", []):
                bw, bh = p.get("w", 0.0) * w, p.get("h", 0.0) * h
                cx, cy = p["x"] * w, p["y"] * h
                _draw_box(
                    frame,
                    cx - bw / 2,
                    cy - bh / 2,
                    cx + bw / 2,
                    cy + bh / 2,
                    _ORANGE,
                    thick,
                    f"Person {p.get('confidence', 0):.2f}",
                    scale,
                )

    # Red: MediaPipe face tracks (held from the nearest sampled frame).
    for tr in _nearest_tracks(ctx["tracked"], ctx["track_times"], t):
        bw, bh = tr.get("w", 0.0) * w, tr.get("h", 0.0) * h
        cx, cy = tr["x"] * w, tr["y"] * h
        if bw <= 0 or bh <= 0:
            bw = bh = 0.08 * w  # fallback marker when no box dims
        label = ctx["labels"].get(tr["track_id"], str(tr["track_id"]))
        cap = f"Track {label} {tr.get('confidence', 0):.2f}"
        if tr.get("mouth") is not None:  # ASD signal (mouth-aspect-ratio)
            cap += f" m{tr['mouth']:.2f}"
        _draw_box(
            frame,
            cx - bw / 2,
            cy - bh / 2,
            cx + bw / 2,
            cy + bh / 2,
            _RED,
            thick,
            cap,
            scale,
        )

    # Top banners: Gemini scene label, then the planner's decision + why.
    lines = []
    scene = _scene_at(ctx["scenes"], ctx["scene_starts"], t)
    if scene:
        parts = [scene.get("scene_type", "scene")]
        if scene.get("active_subject"):
            parts.append(f"focus: {scene['active_subject']}")
        if scene.get("requires_full_width"):
            parts.append("FULL-WIDTH")
        lines.append("  |  ".join(parts))

    # Green: chosen crop window from the reframe plan (if provided).
    seg = (
        _scene_at(ctx["segments"], ctx["segment_starts"], t)
        if ctx["segments"]
        else None
    )
    if seg:
        _draw_crop_window(frame, t, seg, ctx["src_h"])
        trig = (seg.get("trace") or {}).get("trigger") or seg.get("reason")
        if trig:
            lines.append(trig)
    if lines:
        _draw_caption(frame, lines, scale)


def _draw_crop_window(frame, t, seg, src_h):
    h, w = frame.shape[:2]
    inner = seg.get("inner_ar")
    if inner:
        aw, ah = inner
        crop_w = min(int(src_h * aw / ah), w)
    else:  # full-width letterbox
        crop_w = w
    crops = seg.get("crops") or [{}]
    x_frac = _interp_x(crops[0].get("keypoints", []), t)
    left = max(0, min(w - crop_w, int(x_frac * w - crop_w / 2)))
    cv2.rectangle(frame, (left, 0), (left + crop_w, h - 1), _GREEN, max(2, w // 400))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def render_diagnostic(
    src_path: str,
    out_path: str,
    tracked_frames: List[dict],
    scenes: List[dict],
    src_w: int,
    src_h: int,
    segments: Optional[List[dict]] = None,
    has_audio: bool = True,
    person_frames: Optional[List[dict]] = None,
) -> str:
    """Render an annotated 9:16 letterboxed diagnostic video.

    Draws detector overlays on every native-resolution frame, then letterboxes
    the result into 1080×1920 over a blurred background (audio copied from src).
    """
    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise RuntimeError(f"Diagnostic: cannot open {src_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    ctx = {
        "tracked": tracked_frames,
        "track_times": [f["time_sec"] for f in tracked_frames],
        "labels": track_label_map(tracked_frames),
        "scenes": scenes,
        "scene_starts": [s.get("start_sec", 0.0) for s in scenes],
        "segments": segments,
        "segment_starts": [s["start"] for s in segments] if segments else [],
        "persons": person_frames,
        "person_times": [f["time_sec"] for f in person_frames] if person_frames else [],
        "src_h": src_h,
    }

    annotated = tempfile.mkstemp(suffix="_annot.mp4")[1]
    writer = cv2.VideoWriter(
        annotated, cv2.VideoWriter_fourcc(*"mp4v"), fps, (src_w, src_h)
    )
    try:
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            _annotate_frame(frame, idx / fps, ctx)
            writer.write(frame)
            idx += 1
        logger.info(f"Diagnostic: annotated {idx} frames")
    finally:
        cap.release()
        writer.release()

    _letterbox_to_canvas(annotated, src_path, out_path, has_audio)
    return out_path


def _letterbox_to_canvas(annotated, src_path, out_path, has_audio):
    """Scale the annotated 16:9 frame to fit 1080 wide, center over blurred bg."""
    filter_complex = (
        f"[0:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
        f"crop={CANVAS_W}:{CANVAS_H},gblur=sigma=40[bg];"
        f"[0:v]scale={CANVAS_W}:-2[fg];"
        f"[bg][fg]overlay=0:(H-h)/2[v]"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        annotated,
        "-i",
        src_path,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
    ]
    cmd += ["-map", "1:a?"] if has_audio else []
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        out_path,
    ]
    run_ffmpeg(cmd, timeout=1200, label="diagnostic-letterbox")

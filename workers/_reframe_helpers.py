"""Reframe job formatters — turn diarization + face-track data into Gemini context.

Lifted out of `ReframeProcessor` so the processor file stays under the
file-size budget. The formatters are pure; `ensure_cv2_readable` does I/O
(probe + optional transcode) and is kept here to stay out of the processor.
"""

import logging

logger = logging.getLogger(__name__)


def ensure_cv2_readable(src_path: str, tmp, record_id: str = "") -> str:
    """Return a path whose frames OpenCV (cv2) can actually decode.

    Detection is MediaPipe, but every detector is FED frames by OpenCV
    (`cv2.VideoCapture`): face/person detection, scene-cut detection and text
    detection all decode via cv2. OpenCV's FFmpeg backend in the Cloud Run image
    tries HARDWARE AV1 decoding and — with no GPU — reads ZERO frames instead of
    falling back to software. The result: an AV1 (or otherwise cv2-undecodable)
    upload yields NO detections at all, and the planner silently degrades to one
    static center crop over the whole video.

    ffmpeg itself software-decodes AV1 fine (so render + diarization still work),
    so we probe cv2 and, if it can't read a frame, transcode to H.264 for the
    detection passes only — the render keeps using the original. Best-effort: any
    transcode failure returns the original so the job still completes.
    """
    try:
        import cv2
    except Exception:
        return src_path
    cap = cv2.VideoCapture(src_path)
    ok = cap.isOpened() and cap.read()[0]
    cap.release()
    if ok:
        return src_path

    logger.warning(
        f"[reframe:{record_id}] OpenCV cannot decode source frames (likely AV1 / "
        "no HW decode) — transcoding to H.264 for detection so MediaPipe gets frames"
    )
    try:
        from ffmpeg_runner import run_ffmpeg

        out = tmp.create(suffix="_det.mp4")
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-i",
                src_path,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                out,
            ],
            label="reframe-detect-transcode",
        )
        cap2 = cv2.VideoCapture(out)
        ok2 = cap2.isOpened() and cap2.read()[0]
        cap2.release()
        if ok2:
            return out
        logger.warning(f"[reframe:{record_id}] transcoded copy still unreadable by cv2")
    except Exception as e:
        logger.warning(f"[reframe:{record_id}] detection transcode failed ({e})")
    return src_path


def format_chirp_context(speaker_segments: list) -> str:
    """Format Chirp diarization as concise context for Gemini.

    Filters out noise (segments <2s) and keeps only the 30 longest speaker
    turns so we don't overwhelm Gemini with hundreds of micro-segments.
    """
    if not speaker_segments:
        return ""

    significant = [s for s in speaker_segments if s["end_sec"] - s["start_sec"] >= 2.0]
    if not significant:
        significant = speaker_segments[:10]
    significant.sort(key=lambda s: s["start_sec"])
    if len(significant) > 30:
        by_dur = sorted(
            significant, key=lambda s: s["end_sec"] - s["start_sec"], reverse=True
        )[:30]
        significant = sorted(by_dur, key=lambda s: s["start_sec"])

    lines = [
        "=== SPEAKER DIARIZATION ===",
        "These are the major speaker turns detected from audio analysis.",
        "Use these to determine WHO is speaking WHEN and place focal points accordingly.",
        "Each speaker occupies a different position in the frame — track the active speaker.",
        "",
    ]
    for seg in significant:
        dur = seg["end_sec"] - seg["start_sec"]
        lines.append(
            f"[{seg['start_sec']:.1f}s - {seg['end_sec']:.1f}s] {seg['speaker_id']} ({dur:.0f}s)"
        )

    unique = sorted(set(s["speaker_id"] for s in significant))
    lines.append("")
    lines.append(
        f"{len(significant)} speaker turns, {len(unique)} speakers: {', '.join(unique)}"
    )
    return "\n".join(lines)


def _stable_tracks(tracked_frames: list) -> dict[int, list[float]]:
    """Return tracks visible in ≥5% of frames; falls back to top-5 by length."""
    track_data: dict[int, list[float]] = {}
    for frame in tracked_frames:
        for t in frame.get("tracks", []):
            track_data.setdefault(t["track_id"], []).append(t["x"])
    if not track_data:
        return {}
    min_frames = max(3, len(tracked_frames) * 0.05)
    stable = {tid: xs for tid, xs in track_data.items() if len(xs) >= min_frames}
    if not stable:
        stable = dict(sorted(track_data.items(), key=lambda kv: -len(kv[1]))[:5])
    return stable


def _track_position_label(avg_x: float) -> str:
    if avg_x < 0.4:
        return "left"
    if avg_x > 0.6:
        return "right"
    return "center"


def format_track_summary(tracked_frames: list) -> str:
    """Summarize MediaPipe tracks as Gemini context.

    Tells Gemini exactly which face tracks exist and their typical horizontal
    positions so it can reference them by ID (e.g. 'Track A').
    """
    if not tracked_frames:
        return ""
    stable = _stable_tracks(tracked_frames)
    if not stable:
        return ""

    lines = [
        "=== DETECTED FACES (from frame analysis) ===",
        "These are the face tracks detected in the video.",
        "For each scene, reference a track by its label (e.g. 'Track A').",
        "",
    ]
    sorted_tracks = sorted(stable.items(), key=lambda kv: -len(kv[1]))
    for i, (tid, xs) in enumerate(sorted_tracks):
        avg_x = sum(xs) / len(xs)
        pct = len(xs) / len(tracked_frames) * 100
        label = chr(ord("A") + i) if i < 26 else str(tid)
        lines.append(
            f"- Track {label}: typically at x≈{avg_x:.2f} "
            f"({_track_position_label(avg_x)}), visible in {pct:.0f}% of frames"
        )
    lines.append("")
    lines.append(
        f"{len(stable)} main tracks detected. Use 'Track A', 'Track B', etc. "
        f"as active_subject, or 'left'/'right'/'center' for spatial hints."
    )
    return "\n".join(lines)

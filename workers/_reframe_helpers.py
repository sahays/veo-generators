"""Reframe job formatters — turn diarization + face-track data into Gemini context.

Lifted out of `ReframeProcessor` so the processor file stays under the
file-size budget. Both functions are pure (no I/O) — they just stringify
already-fetched data into a prompt-ready context block.
"""


def format_chirp_context(speaker_segments: list) -> str:
    """Format Chirp diarization as concise context for Gemini.

    Filters out noise (segments <2s) and keeps only the 30 longest speaker
    turns so we don't overwhelm Gemini with hundreds of micro-segments.
    """
    if not speaker_segments:
        return ""

    significant = [
        s for s in speaker_segments if s["end_sec"] - s["start_sec"] >= 2.0
    ]
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

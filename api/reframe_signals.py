"""Per-window signal aggregation for the reframe planner.

Everything here turns raw detector/diarization series into per-segment facts —
stable tracks, mouth activity, speech spans, speaker turns, the wide-text band,
focal series. No decisions are made here: `reframe_plan._decide_segment`
consumes these facts and chooses layouts/escalations. Pure logic, no I/O.
"""

import bisect
import re
import statistics
from typing import List, Optional, Tuple

STABLE_FRAC = 0.30  # a track must appear in ≥ this fraction of segment frames

# Active-speaker detection (Phase 2): in a multi-person shot, frame the talking
# face (mouth moving) as a single crop instead of letterboxing both. Speaking is
# measured as the variance of each track's mouth-aspect-ratio over the segment.
# Detection samples at ~1 fps, so a ≤5s segment yields at most ~5 MAR samples —
# a tiny series where landmark jitter / laughing / chewing easily fakes variance.
# The bar is set high on purpose: a FALSE pin silently tight-crops one face and
# bypasses keep-both AND the Gemini escalation, while a missed pin merely
# escalates (Gemini still centers the right person). Only a clearly dominant
# talker should resolve deterministically.
SPEAKER_MIN_SAMPLES = 4  # need this many mouth samples to judge a track
SPEAKER_MIN_ACTIVITY = 0.05  # MAR stdev below this = not talking
SPEAKER_DOMINANCE = 2.5  # the speaker's activity must beat the 2nd by this factor

# Diarization-derived dialogue signal. The dense Gemini scene pass (which used to
# label "dialogue" / "side_by_side") was retired, so keep-both and split would
# never fire in production (scene is always {}). Chirp diarization already runs;
# a window where two distinct speakers each hold the floor for ≥ this many seconds
# IS the two-person-dialogue signal those layouts need. Supplied to reconcile as
# `speaker_segments` and injected as scene_type="dialogue" when no scene label set.
DIALOGUE_MIN_SPEAK = 0.5  # seconds a speaker must talk in a window to count
# Active-speaker centering: in a multi-person shot only one person speaks at a time
# and that speaker must be centered. Mouth-motion (MAR) alone is noisy (laughing /
# chewing), so we measure it ONLY over frames where diarization says someone is
# speaking (audio↔face association) — and re-cut a shot when the dominant speaker
# changes so the framing follows the turn. SPEAKER_TURN_MIN_DWELL keeps quick
# back-and-forth from fragmenting the plan into sub-second flips. Kept ≥ MIN_DWELL
# so a turn re-cut doesn't itself create a sub-dwell fragment that `_merge_short`
# immediately folds away (which would defeat the re-cut).
SPEAKER_TURN_MIN_DWELL = 2.0  # min seconds between speaker-change re-cuts

# On-screen text detection (Phase 2): the CPU flags a persistent text band so the
# planner can ask Gemini the right question when a crop would clip it (decision
# point #1). The CPU never self-letterboxes from it — see _maybe_text_escalation.
# Significance is deliberately NOT a total-width floor: a detected line is already
# ≥ _MIN_LINE_W (0.20) wide by construction, and the poke-out test (SIDE_TEXT_MARGIN)
# establishes the *conflict*; Gemini arbitrates every escalation, so err low. A
# wide-coverage floor silently cropped animated / narrow-but-peripheral captions
# (rf-r5eik9j2: a product ad's callouts read 0.28-0.29 wide and were dropped) — the
# cost of a false band over a busy background is only a thumbnail question.
TEXT_PERSIST_FRAC = (
    0.50  # text must be present in ≥ this fraction of a segment's frames
)
TEXT_MIN_FRAMES = 2  # ...and in at least this many frames (one sample ≠ persistent)


# ---------------------------------------------------------------------------
# Track aggregation within a time window
# ---------------------------------------------------------------------------


def _global_label_map(tracked_frames: List[dict]) -> dict:
    """label (A,B,…) → track_id, ranked by global visibility (matches Gemini context)."""
    counts: dict = {}
    for frame in tracked_frames:
        for t in frame.get("tracks", []):
            counts[t["track_id"]] = counts.get(t["track_id"], 0) + 1
    ranked = sorted(counts, key=lambda tid: -counts[tid])
    return {
        (chr(ord("A") + i) if i < 26 else str(tid)): tid for i, tid in enumerate(ranked)
    }


def _window(frames, times, start, end):
    """Frames whose time_sec is in [start, end], via bisect on the prebuilt
    `times` index.

    `times` is a once-computed sorted list of each frame's time_sec, aligned with
    `frames`. Slicing through it makes every per-segment aggregation O(log F + w)
    over its window instead of an O(F) rescan of the whole series per segment.
    """
    lo = bisect.bisect_left(times, start)
    hi = bisect.bisect_right(times, end)
    return frames[lo:hi]


def _stable_tracks(win):
    """Mean x/w and visibility fraction per track over the windowed frames."""
    if not win:
        return []
    agg: dict = {}
    for f in win:
        for t in f.get("tracks", []):
            a = agg.setdefault(t["track_id"], {"xs": [], "ws": [], "cs": []})
            a["xs"].append(t["x"])
            a["ws"].append(t.get("w", 0.0))
            a["cs"].append(t.get("confidence", 0.5))
    n = len(win)
    stats = [
        {
            "track_id": tid,
            "x": sum(a["xs"]) / len(a["xs"]),
            "w": sum(a["ws"]) / len(a["ws"]),
            "conf": sum(a["cs"]) / len(a["cs"]),
            "frac": len(a["xs"]) / n,
        }
        for tid, a in agg.items()
    ]
    return [s for s in stats if s["frac"] >= STABLE_FRAC]


# ---------------------------------------------------------------------------
# Entity matching (Gemini hint → a concrete track)
# ---------------------------------------------------------------------------


def _hint_x(scene: dict) -> float:
    h = (scene.get("active_subject") or "").lower()
    if "left" in h:
        return 0.3
    if "right" in h:
        return 0.7
    return 0.5


def _match_track(stable: List[dict], scene: dict, label_map: dict) -> dict:
    """Resolve the active subject to one stable track (geometric, not id-order)."""
    h = (scene.get("active_subject") or "").lower()
    m = re.search(r"track\s+([a-z])", h)
    if m:
        tid = label_map.get(m.group(1).upper())
        match = next((s for s in stable if s["track_id"] == tid), None)
        if match:
            return match
    if "left" in h:
        return min(stable, key=lambda s: s["x"])
    if "right" in h:
        return max(stable, key=lambda s: s["x"])
    if "center" in h:
        return min(stable, key=lambda s: abs(s["x"] - 0.5))
    return max(stable, key=lambda s: s["frac"])  # most prominent


def _scene_for(
    scenes: List[dict], starts: List[float], start: float, end: float
) -> dict:
    """The Gemini scene covering this segment's midpoint (empty dict if none)."""
    if not scenes:
        return {}
    mid = (start + end) / 2
    i = bisect.bisect_right(starts, mid) - 1
    return scenes[max(0, i)] if i >= 0 else scenes[0]


# ---------------------------------------------------------------------------
# Speaker / diarization signals
# ---------------------------------------------------------------------------


def pick_active_speaker(track_mouth: dict) -> Optional[int]:
    """Track id of the clearly-talking face, or None if ambiguous/silent.

    `track_mouth` maps track_id → list of mouth-aspect-ratio samples over the
    window. Talking makes the ratio oscillate (high variance); a listener's
    mouth is ~steady. Returns a speaker only when one track's activity clearly
    dominates — otherwise None so the caller keeps both in frame.
    """
    acts = {
        tid: statistics.pstdev(v)
        for tid, v in track_mouth.items()
        if len(v) >= SPEAKER_MIN_SAMPLES
    }
    if not acts:
        return None
    ranked = sorted(acts.items(), key=lambda kv: -kv[1])
    top_tid, top = ranked[0]
    if top < SPEAKER_MIN_ACTIVITY:
        return None  # nobody clearly talking
    if len(ranked) > 1 and ranked[1][1] * SPEAKER_DOMINANCE > top:
        return None  # two mouths moving → ambiguous, keep both
    return top_tid


def _segment_track_mouth(win, track_ids, speech_intervals=None) -> dict:
    """Per-track mouth-aspect-ratio samples over the windowed frames.

    When `speech_intervals` (clipped (lo, hi) spans where diarization says SOMEONE
    is speaking) is given, only frames inside a span are sampled — so a steady
    listener and stray motion during silence don't register as "talking". With no
    intervals (no audio) it falls back to every frame (vision-only behaviour).
    """
    ids = set(track_ids)
    out: dict = {tid: [] for tid in ids}
    for f in win:
        if speech_intervals and not _in_intervals(f["time_sec"], speech_intervals):
            continue
        for tr in f.get("tracks", []):
            m = tr.get("mouth")
            if tr["track_id"] in ids and m is not None:
                out[tr["track_id"]].append(m)
    return out


def _in_intervals(t: float, intervals: List[Tuple[float, float]]) -> bool:
    return any(lo <= t <= hi for lo, hi in intervals)


def _speech_intervals(speaker_segments, start: float, end: float):
    """Diarization speech spans clipped to [start, end] (any speaker talking)."""
    out: List[Tuple[float, float]] = []
    for sp in speaker_segments or []:
        lo = max(start, sp.get("start_sec", 0.0))
        hi = min(end, sp.get("end_sec", 0.0))
        if hi > lo:
            out.append((lo, hi))
    return out


def _dominant_speaker(speaker_segments, start: float, end: float):
    """speaker_id talking the most in [start, end], or None. Used to key the
    active_speaker escalation so different-speaker turns stay distinct through
    `_merge_short`, while same-speaker MAX_SEG_LEN subdivisions still recombine."""
    talk: dict = {}
    for sp in speaker_segments or []:
        lo = max(start, sp.get("start_sec", 0.0))
        hi = min(end, sp.get("end_sec", 0.0))
        if hi > lo:
            sid = sp.get("speaker_id")
            talk[sid] = talk.get(sid, 0.0) + (hi - lo)
    return max(talk, key=talk.get) if talk else None


def _associate_speaker_face(stable, win, speech_intervals):
    """Track id of the face that is speaking (audio↔face), or None if unclear.

    Measures mouth motion ONLY during diarized speech and reuses the same
    dominance test as `pick_active_speaker`. None when nobody clearly wins, when
    the speaker's face isn't on screen, or when there's no speech to anchor on.
    """
    if not stable or not speech_intervals:
        return None
    mouth = _segment_track_mouth(win, [s["track_id"] for s in stable], speech_intervals)
    return pick_active_speaker(mouth)


def _speaker_turn_cuts(speaker_segments, min_dwell: float) -> List[float]:
    """Times where the dominant audio speaker changes — extra cut points so a shot
    re-frames onto the new speaker. Turns closer than `min_dwell` are skipped so a
    rapid back-and-forth doesn't shred the plan into sub-second segments."""
    segs = sorted(
        (
            s
            for s in (speaker_segments or [])
            if s.get("end_sec", 0) > s.get("start_sec", 0)
        ),
        key=lambda s: s.get("start_sec", 0.0),
    )
    cuts: List[float] = []
    prev_speaker = None
    last = None
    for s in segs:
        sid = s.get("speaker_id")
        t = s.get("start_sec", 0.0)
        if sid != prev_speaker and (last is None or t - last >= min_dwell):
            if last is not None:  # don't cut at the very first turn (t≈0)
                cuts.append(t)
            last = t
        prev_speaker = sid
    return cuts


def _dialogue_in_window(speaker_segments: List[dict], start: float, end: float) -> bool:
    """True if ≥2 distinct speakers each hold the floor within [start, end].

    Replaces the retired Gemini "dialogue" scene label with the diarization signal
    that already runs: a window where two speaker_ids each speak ≥ DIALOGUE_MIN_SPEAK
    seconds is a genuine two-person dialogue — the semantic keep-both / split need.
    Geometry gates (separation, static, dwell) still decide the layout downstream;
    this only unlocks the *intent*. `speaker_segments` are dicts with speaker_id /
    start_sec / end_sec (Chirp diarization output).
    """
    if not speaker_segments:
        return False
    talk: dict = {}
    for sp in speaker_segments:
        lo = max(start, sp.get("start_sec", 0.0))
        hi = min(end, sp.get("end_sec", 0.0))
        if hi > lo:
            sid = sp.get("speaker_id")
            talk[sid] = talk.get(sid, 0.0) + (hi - lo)
    return sum(1 for d in talk.values() if d >= DIALOGUE_MIN_SPEAK) >= 2


# ---------------------------------------------------------------------------
# Wide-text coverage (Gemini flags, CPU measures the exact extent)
# ---------------------------------------------------------------------------


def _segment_text_band(win) -> Tuple[float, Tuple[float, float]]:
    """Median text coverage AND its horizontal span over the window.

    `win` is the `text_detect.scan_video_text` frames in this segment (each with
    `coverage` and `span`). Persistence is measured on text *presence*, not on
    instantaneous width: on-screen callouts animate (type / fade in and out), so a
    continuously-displayed caption swings in measured width frame-to-frame and a
    "wide in ≥ half the frames" gate drops it (observed on rf-r5eik9j2 — the
    product-ad callouts read 0.28-0.29 wide yet were persistently on screen). A
    frame with ANY detected line (`coverage > 0` ⟹ a ≥ _MIN_LINE_W line exists)
    counts as present; requiring presence in ≥ TEXT_PERSIST_FRAC of the window
    (and ≥ TEXT_MIN_FRAMES) still rejects a one-frame flash / swish-pan title.

    Returns the median coverage over the present frames plus the median (x0, x1)
    of that band. The span is what lets the planner ask the right question: a band
    that sits *behind* the subject is harmless, but one that extends past the crop
    window on a side would be clipped — the ambiguous "is that meaningful side
    text/graphics?" case that escalates to Gemini (see _maybe_text_escalation).
    """
    if not win:
        return 0.0, (0.0, 0.0)
    present = [f for f in win if f["coverage"] > 0.0]
    if len(present) < TEXT_MIN_FRAMES or len(present) / len(win) < TEXT_PERSIST_FRAC:
        return 0.0, (0.0, 0.0)
    cov = statistics.median([f["coverage"] for f in present])
    x0 = statistics.median([f.get("span", (0.0, 0.0))[0] for f in present])
    x1 = statistics.median([f.get("span", (0.0, 0.0))[1] for f in present])
    return cov, (x0, x1)


# ---------------------------------------------------------------------------
# Per-frame focal series (for intra-segment panning)
# ---------------------------------------------------------------------------


def _track_series(win, track_id):
    """The chosen face track's (time, x, y) samples over the windowed frames."""
    out = []
    for f in win:
        for tr in f.get("tracks", []):
            if tr["track_id"] == track_id:
                out.append(
                    {"time_sec": f["time_sec"], "x": tr["x"], "y": tr.get("y", 0.5)}
                )
                break
    return out


def _track_x_spread(win, track_id) -> float:
    """Range of a track's x center across the windowed frames (0 if absent)."""
    xs = [p["x"] for p in _track_series(win, track_id)]
    return (max(xs) - min(xs)) if xs else 0.0


def _segment_persons(win):
    """Per-frame largest person over the windowed frames → {time_sec, x, y, w}."""
    out = []
    for f in win:
        ps = f.get("persons", [])
        if not ps:
            continue
        big = max(ps, key=lambda p: p.get("w", 0.0) * p.get("h", 0.0))
        out.append(
            {
                "time_sec": f["time_sec"],
                "x": big["x"],
                "y": big.get("y", 0.5),
                "w": big.get("w", 0.0),
            }
        )
    return out

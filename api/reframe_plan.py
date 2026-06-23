"""Reframe v2 decision layer — turn detections into a per-segment crop plan.

Pure logic: no I/O, no cv2/ffmpeg. Reconciles Gemini scene labels (the *what*)
with MediaPipe face tracks (the *where*) to choose, per scene, an inner aspect
ratio (how much to crop vs. letterbox) and which subject(s) to follow.

Output is a list of SegmentPlan dicts consumed by the renderer:
    {start, end, layout, inner_ar, crops:[{track_id, x_target, keypoints}], reason}
"""

import bisect
import math
import statistics
from typing import List, Optional, Tuple

# Inner-AR rungs, tightest crop → loosest (most letterbox). Chosen by coverage.
# 9:16 is the historical *adaptive* ladder: each scene picks a rung, letterboxing
# wide content. 3:4 is a *fixed* full-bleed crop — a single-rung ladder so every
# scene crops to fill the 3:4 frame (subject-following pan), never letterboxes.
RUNGS: List[Tuple[int, int]] = [(9, 16), (4, 5), (1, 1), (16, 9)]
RUNGS_BY_CANVAS: dict = {
    "9:16": RUNGS,
    "3:4": [(3, 4)],
}

MIN_DWELL = 2.0  # merge segments shorter than this (seconds)
MAX_SEG_LEN = 5.0  # re-decide framing at least this often, even with no cut
MERGE_X_TOL = 0.08  # only merge same-framing neighbours if the crop center agrees
COVERAGE_MARGIN = 0.04  # safety margin added to measured detection width
RUNG_TOLERANCE = 0.05  # accept a rung that covers within this of the requirement
KEEP_BOTH_SEPARATION = 0.30  # min face-center separation for keep-both
STABLE_FRAC = 0.30  # a track must appear in ≥ this fraction of segment frames
# A single subject can never need full width — cap its coverage demand so a huge
# (foreground / mis-measured) detection doesn't force 16:9 letterbox.
FACE_W_CAP = 0.45  # → at most 1:1 from a single face
PERSON_W_CAP = 0.60  # bodies are wider than faces, but still bounded

# Active-speaker detection (Phase 2): in a multi-person shot, frame the talking
# face (mouth moving) as a single crop instead of letterboxing both. Speaking is
# measured as the variance of each track's mouth-aspect-ratio over the segment.
SPEAKER_MIN_SAMPLES = 3  # need this many mouth samples to judge a track
SPEAKER_MIN_ACTIVITY = 0.03  # MAR stdev below this = not talking
SPEAKER_DOMINANCE = 1.6  # the speaker's activity must beat the 2nd by this factor

# Wide-text detection (Phase 2): a CPU-measured text-line width refines Gemini's
# coarse full-width flag so we letterbox to the real text extent, not a blanket
# 1.0. "Gemini understands, CPU locates" — see reconcile_text_coverage.
TEXT_WIDE_MIN = 0.50  # a sampled frame counts as wide-text at/above this coverage
TEXT_PERSIST_FRAC = 0.50  # text must show in ≥ this fraction of a segment's frames
TEXT_SELF_TRIGGER = 0.70  # CPU may letterbox unprompted only above this width

# Vertical-split layout (Phase 3): when two speakers sit too far apart for even a
# 1:1 rung to hold both at a decent size, stack them as two full-canvas panels so
# both read large. Stacking destroys eyeline/spatial continuity, so it is gated
# hard — only a *static, persistent, two-person dialogue* qualifies; everything
# else keeps the single/keep-both crop. left subject → top panel, right → bottom.
SPLIT_MIN_SEPARATION = 0.45  # face-center gap above which 1:1 shrinks both too far
SPLIT_MIN_FRAC = 0.80  # both tracks must be near-continuously present
SPLIT_MIN_DWELL = 3.0  # only for shots that hold long enough to read as intentional
SPLIT_MAX_MOTION = 0.06  # near-static: each track's x-span must stay below this

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
# If the subject's x barely moves across a segment, center on its median
# position (robust to boundary jitter) instead of a velocity-limited path that
# can lock off-center.
STATIC_SPREAD = 0.10


# ---------------------------------------------------------------------------
# Rung selection
# ---------------------------------------------------------------------------


def rung_coverage(rung: Tuple[int, int], src_w: int, src_h: int) -> float:
    """Fraction of source width a rung's crop keeps (clamped to 1.0)."""
    aw, ah = rung
    return min(1.0, (src_h * aw / ah) / src_w)


def pick_rung(
    required: float,
    src_w: int,
    src_h: int,
    prev: Optional[Tuple[int, int]] = None,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> Tuple[int, int]:
    """Lowest rung whose coverage ≥ required.

    Hysteresis: if the previous rung still covers the content and is at most one
    rung looser than ideal, keep it (avoids single-step flip-flopping). A larger
    gap still tightens so we never stay needlessly letterboxed.

    A small RUNG_TOLERANCE lets a tighter rung win when it *almost* covers the
    requirement — trading a sliver of edge crop for much less letterboxing (e.g.
    a two-shot needing 0.60 takes 1:1 at 0.5625 rather than full 16:9).

    `rungs` is the canvas's ladder (defaults to the 9:16 RUNGS).
    """
    rungs = rungs or RUNGS
    ideal = next(
        (
            r
            for r in rungs
            if rung_coverage(r, src_w, src_h) + RUNG_TOLERANCE >= required
        ),
        rungs[-1],
    )
    if (
        prev is not None
        and prev in rungs
        and rung_coverage(prev, src_w, src_h) + RUNG_TOLERANCE >= required
    ):
        if 0 <= rungs.index(prev) - rungs.index(ideal) <= 1:
            return prev
    return ideal


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


def _stable_tracks(tracked_frames, start, end):
    """Mean x/w and visibility fraction per track within [start, end]."""
    times = [f["time_sec"] for f in tracked_frames]
    lo = bisect.bisect_left(times, start)
    hi = bisect.bisect_right(times, end)
    frames = tracked_frames[lo:hi]
    if not frames:
        return []
    agg: dict = {}
    for f in frames:
        for t in f.get("tracks", []):
            a = agg.setdefault(t["track_id"], {"xs": [], "ws": []})
            a["xs"].append(t["x"])
            a["ws"].append(t.get("w", 0.0))
    n = len(frames)
    stats = [
        {
            "track_id": tid,
            "x": sum(a["xs"]) / len(a["xs"]),
            "w": sum(a["ws"]) / len(a["ws"]),
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
    import re

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


def _segment_track_mouth(tracked_frames, track_ids, start, end) -> dict:
    """Per-track mouth-aspect-ratio samples within [start, end]."""
    ids = set(track_ids)
    out: dict = {tid: [] for tid in ids}
    for f in tracked_frames:
        t = f["time_sec"]
        if t < start or t > end:
            continue
        for tr in f.get("tracks", []):
            m = tr.get("mouth")
            if tr["track_id"] in ids and m is not None:
                out[tr["track_id"]].append(m)
    return out


def _keep_both_pair(stable: List[dict], scene: dict):
    """Return the two far-apart tracks to keep, or None for a single-subject crop."""
    if len(stable) < 2:
        return None
    layout = (scene.get("layout") or "").lower()
    by_vis = sorted(stable, key=lambda s: -s["frac"])[:2]
    sep = abs(by_vis[0]["x"] - by_vis[1]["x"])
    wants_both = layout == "side_by_side" or scene.get("scene_type") == "dialogue"
    if sep >= KEEP_BOTH_SEPARATION and (wants_both or sep >= 0.45):
        return by_vis
    return None


def _track_x_spread(tracked_frames, track_id, start, end) -> float:
    """Range of a track's x center across [start, end] (0 if absent)."""
    xs = [p["x"] for p in _track_series(tracked_frames, track_id, start, end)]
    return (max(xs) - min(xs)) if xs else 0.0


def _split_crops(pair, tracked_frames, start, end, scene):
    """Two stacked panels for a static, far-apart two-person dialogue, or None.

    Gated hard (stacking breaks eyeline continuity): the two tracks must be widely
    separated, both near-continuously present, the shot must hold long enough to
    read, both panels must be near-static, and Gemini must call it a dialogue /
    side-by-side. Assignment is geometric and stable — left subject → top panel,
    right → bottom — so panels never swap mid-scene.
    """
    a, b = pair
    if abs(a["x"] - b["x"]) < SPLIT_MIN_SEPARATION:
        return None
    if min(a["frac"], b["frac"]) < SPLIT_MIN_FRAC:
        return None
    if (end - start) < SPLIT_MIN_DWELL:
        return None
    layout = (scene.get("layout") or "").lower()
    if scene.get("scene_type") != "dialogue" and layout != "side_by_side":
        return None
    left, right = sorted(pair, key=lambda s: s["x"])  # left → top, right → bottom
    if (
        _track_x_spread(tracked_frames, left["track_id"], start, end) > SPLIT_MAX_MOTION
        or _track_x_spread(tracked_frames, right["track_id"], start, end)
        > SPLIT_MAX_MOTION
    ):
        return None
    return [
        {"track_id": left["track_id"], "x_target": left["x"], "source": "split_top"},
        {
            "track_id": right["track_id"],
            "x_target": right["x"],
            "source": "split_bottom",
        },
    ]


# ---------------------------------------------------------------------------
# Wide-text coverage (Gemini flags, CPU measures the exact extent)
# ---------------------------------------------------------------------------


def _segment_text_coverage(text_frames, start, end) -> float:
    """Median wide-text coverage over [start, end], or 0 if text isn't persistent.

    `text_frames` is `text_detect.scan_video_text` output. Requires wide text in
    ≥ TEXT_PERSIST_FRAC of the segment's sampled frames (rejects a one-frame
    flash / a swish-pan title), then returns the median width of the frames that
    *did* carry it.
    """
    if not text_frames:
        return 0.0
    seg = [f for f in text_frames if start <= f["time_sec"] <= end]
    if not seg:
        return 0.0
    wide = [f["coverage"] for f in seg if f["coverage"] >= TEXT_WIDE_MIN]
    if len(wide) / len(seg) < TEXT_PERSIST_FRAC:
        return 0.0
    return statistics.median(wide)


def reconcile_text_coverage(
    gemini_c: float, measured: float, gemini_text_intent: bool
) -> float:
    """Combine Gemini's text flag with the CPU-measured text width → C_text.

    "Gemini understands, CPU locates":
    - Gemini says the shot has wide text AND the detector found a band → trust the
      *measured* extent (precise — a 0.7-wide title takes 1:1, not a needless full
      16:9 letterbox).
    - Gemini says text but the detector found none → keep Gemini's number (the
      detector may have missed it; never chop content Gemini flagged).
    - Gemini didn't flag text → trust the detector only when it's confidently wide
      (guards against textured-background false positives forcing letterbox).
    """
    if gemini_text_intent:
        return measured if measured > 0.0 else gemini_c
    if measured >= TEXT_SELF_TRIGGER:
        return measured
    return gemini_c


# ---------------------------------------------------------------------------
# Per-frame focal series (for intra-segment panning)
# ---------------------------------------------------------------------------


def _track_series(tracked_frames, track_id, start, end):
    """The chosen face track's (time, x, y) samples within [start, end]."""
    out = []
    for f in tracked_frames:
        t = f["time_sec"]
        if t < start or t > end:
            continue
        for tr in f.get("tracks", []):
            if tr["track_id"] == track_id:
                out.append({"time_sec": t, "x": tr["x"], "y": tr.get("y", 0.5)})
                break
    return out


def _segment_persons(person_frames, start, end):
    """Per-frame largest person within [start, end] → {time_sec, x, y, w}."""
    out = []
    for f in person_frames or []:
        t = f["time_sec"]
        if t < start or t > end:
            continue
        ps = f.get("persons", [])
        if not ps:
            continue
        big = max(ps, key=lambda p: p.get("w", 0.0) * p.get("h", 0.0))
        out.append(
            {
                "time_sec": t,
                "x": big["x"],
                "y": big.get("y", 0.5),
                "w": big.get("w", 0.0),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-segment decision (always one crop in the MVP; split is Phase 3)
# ---------------------------------------------------------------------------


def _competitors(stable, mouth) -> list:
    """Compact per-face record (for the decision trace / observability)."""
    out = []
    for s in stable:
        m = mouth.get(s["track_id"], []) if mouth else []
        out.append(
            {
                "track_id": s["track_id"],
                "x": round(s["x"], 3),
                "w": round(s["w"], 3),
                "frac": round(s["frac"], 2),
                "mouth_var": round(statistics.pstdev(m), 3) if len(m) >= 3 else None,
            }
        )
    return out


def _decide_segment(
    scene, tracked_frames, person_frames, start, end, label_map, text_frames=None
):
    """Decide layout, focal target and required coverage for one segment.

    Falls back to person/body detection when no stable face is present (e.g. a
    subject walking away), then to the Gemini spatial hint. Returns the decision
    plus the raw inputs that drove it (for the decision trace).
    """
    stable = _stable_tracks(tracked_frames, start, end)
    gemini_c = (
        1.0
        if scene.get("requires_full_width")
        else float(scene.get("min_horizontal_coverage") or 0.0)
    )
    # Gemini "means text" when it flags full-width, names a text/slide layout, or
    # asks for near-full coverage — that's when a measured text band should win.
    text_intent = (
        bool(scene.get("requires_full_width"))
        or (scene.get("layout") or "").lower() in ("text_card", "slide")
        or gemini_c >= 0.8
    )
    text_meas = _segment_text_coverage(text_frames, start, end)
    c_text = reconcile_text_coverage(gemini_c, text_meas, text_intent)

    def out(layout, crop, c, c_meas, faces=None, n_persons=0):
        return {
            "layout": layout,
            "crops": [crop],
            "C": min(1.0, c),
            "c_text": c_text,
            "gemini_c": gemini_c,
            "text_meas": round(text_meas, 3),
            "c_meas": round(c_meas, 3),
            "source": crop["source"],
            "n_faces": len(stable),
            "n_persons": n_persons,
            "faces": faces or [],
        }

    # Margin pads the DETECTION-measured width (for tracker slop), not Gemini's
    # stated coverage (which is already a minimum) — avoids double-padding.
    if stable:
        mouth = _segment_track_mouth(
            tracked_frames, [s["track_id"] for s in stable], start, end
        )
        faces = _competitors(stable, mouth)
        pair = _keep_both_pair(stable, scene)
        if pair:
            speaker = pick_active_speaker(mouth)
            tgt = next((s for s in stable if s["track_id"] == speaker), None)
            if tgt:  # ASD: one of the two is clearly talking → frame them large
                cm = min(tgt["w"], FACE_W_CAP)
                crop = {"track_id": speaker, "x_target": tgt["x"], "source": "speaker"}
                return out("single", crop, max(cm + COVERAGE_MARGIN, c_text), cm, faces)

            # Neither clearly dominates: if they're too far apart for 1:1 to hold
            # both large AND the shot is a static dialogue, stack them as panels
            # instead of letterboxing both tiny.
            split = _split_crops(pair, tracked_frames, start, end, scene)
            if split:
                a, b = pair
                sep = abs(a["x"] - b["x"])
                return {
                    "layout": "split",
                    "crops": split,
                    "C": 1.0,  # panels fill the canvas; no rung / letterbox
                    "c_text": c_text,
                    "gemini_c": gemini_c,
                    "text_meas": round(text_meas, 3),
                    "c_meas": round(sep, 3),
                    "source": "split",
                    "n_faces": len(stable),
                    "n_persons": 0,
                    "faces": faces,
                }

            a, b = pair
            left = min(a["x"] - a["w"] / 2, b["x"] - b["w"] / 2)
            right = max(a["x"] + a["w"] / 2, b["x"] + b["w"] / 2)
            span = max(0.0, right - left)
            crop = {
                "track_id": None,
                "x_target": (a["x"] + b["x"]) / 2,
                "source": "center",
            }
            return out(
                "keep_both", crop, max(span + COVERAGE_MARGIN, c_text), span, faces
            )

        tgt = _match_track(stable, scene, label_map)
        cm = min(tgt["w"], FACE_W_CAP)
        crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": "face"}
        return out("single", crop, max(cm + COVERAGE_MARGIN, c_text), cm, faces)

    # No stable face → try person/body detection.
    persons = _segment_persons(person_frames, start, end)
    seg_frames = [f for f in (person_frames or []) if start <= f["time_sec"] <= end]
    if persons and len(persons) / max(1, len(seg_frames)) >= STABLE_FRAC:
        mean_x = sum(p["x"] for p in persons) / len(persons)
        mean_w = min(sum(p["w"] for p in persons) / len(persons), PERSON_W_CAP)
        crop = {"track_id": None, "x_target": mean_x, "source": "person"}
        return out(
            "single",
            crop,
            max(mean_w + COVERAGE_MARGIN, c_text),
            mean_w,
            n_persons=len(persons),
        )

    # Nothing detected → Gemini spatial hint, rely on c_text.
    crop = {"track_id": None, "x_target": _hint_x(scene), "source": "center"}
    return out("single", crop, c_text, 0.0)


# ---------------------------------------------------------------------------
# Segmentation + merging
# ---------------------------------------------------------------------------


def _boundaries(cuts: List[float], duration: float) -> List[Tuple[float, float]]:
    """Segment boundaries from cuts, subdivided so no segment exceeds MAX_SEG_LEN.

    Subdivision makes framing robust to missed cuts: a long take (or a stretch
    where cut detection failed) is re-decided every ~MAX_SEG_LEN seconds instead
    of being one stale crop. Identical neighbours are recombined later by merge.
    """
    pts = sorted({0.0, duration, *[c for c in cuts if 0.0 < c < duration]})
    out: List[Tuple[float, float]] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, math.ceil((b - a) / MAX_SEG_LEN))
        step = (b - a) / n
        for k in range(n):
            out.append((a + k * step, b if k == n - 1 else a + (k + 1) * step))
    return out


def _scene_for(
    scenes: List[dict], starts: List[float], start: float, end: float
) -> dict:
    """The Gemini scene covering this segment's midpoint (empty dict if none)."""
    if not scenes:
        return {}
    mid = (start + end) / 2
    i = bisect.bisect_right(starts, mid) - 1
    return scenes[max(0, i)] if i >= 0 else scenes[0]


def _merge_short(
    segments: List[dict],
    min_dwell: float,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> List[dict]:
    """Collapse identical neighbors and fold sub-dwell segments into the previous one."""
    if not segments:
        return []
    rungs = rungs or RUNGS

    def _cx(s):
        return s["crops"][0].get("x_target", 0.5)

    out = [dict(segments[0])]
    for seg in segments[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dwell
        # Same framing AND the crop is on the same spot — otherwise keep separate
        # so each subdivided cell re-frames its own subject (don't smear a pan
        # across two different subjects).
        same = (
            seg["inner_ar"] == prev["inner_ar"]
            and seg["layout"] == prev["layout"]
            and abs(_cx(seg) - _cx(prev)) <= MERGE_X_TOL
        )
        if same or too_short:
            # Extend prev; keep the looser rung so we never crop out the short bit.
            # The looser-rung swap only applies between two rung-based segments —
            # a split (inner_ar=None) has no rung index, so it never swaps in/out
            # here (its strict dwell gate already keeps it from being this short).
            prev["end"] = seg["end"]
            both_runged = isinstance(seg["inner_ar"], tuple) and isinstance(
                prev["inner_ar"], tuple
            )
            if both_runged and rungs.index(seg["inner_ar"]) > rungs.index(
                prev["inner_ar"]
            ):
                prev["inner_ar"] = seg["inner_ar"]
                prev["layout"] = seg["layout"]
                prev["crops"] = seg["crops"]
                prev["reason"] = seg["reason"]
                prev["trace"] = seg.get("trace")
        else:
            out.append(dict(seg))
    return out


def _attach_focal_points(seg, tracked_frames, person_frames):
    """Attach the raw (time, x, y) focal series each crop should follow."""
    start, end = seg["start"], seg["end"]
    for crop in seg["crops"]:
        src = crop.get("source")
        if src in ("face", "speaker", "split_top", "split_bottom"):
            pts = _track_series(tracked_frames, crop["track_id"], start, end)
        elif src == "person":
            pts = [
                {"time_sec": p["time_sec"], "x": p["x"], "y": p["y"]}
                for p in _segment_persons(person_frames, start, end)
            ]
        else:
            pts = []
        crop["focal_points"] = pts or [
            {"time_sec": start, "x": crop.get("x_target", 0.5), "y": 0.5}
        ]


def _fill_keypoints(seg: dict) -> None:
    """Static fallback keypoints so a segment is renderable before smoothing."""
    for crop in seg["crops"]:
        x = crop.get("x_target", 0.5)
        crop["keypoints"] = [(seg["start"], x, 0.5), (seg["end"], x, 0.5)]


def _decision_trace(d, scene, chosen, ideal, src_w, src_h) -> dict:
    """Structured 'why this framing' record + one-line trigger (observability)."""
    cov = rung_coverage(chosen, src_w, src_h)
    ct, cm = d["c_text"], d["c_meas"]
    tmeas = d.get("text_meas", 0.0)
    src, layout = d["source"], d["layout"]
    # Did measured wide-text set C_text (vs. Gemini's coarse number)?
    text_drove = tmeas > 0.0 and abs(ct - tmeas) < 1e-6
    if layout == "keep_both":
        why = f"two faces span {cm:.2f}"
    elif src == "speaker":
        why = "active speaker (mouth movement)"
    elif src == "person":
        why = f"no face; person body w={cm:.2f}"
    elif ct >= cm and text_drove:
        why = f"wide text w={tmeas:.2f} (measured)"
    elif d["n_faces"] == 0:
        why = f"no detection; Gemini coverage {ct:.2f}" if ct > 0 else "no detection"
    elif ct >= cm:
        why = f"Gemini coverage {ct:.2f}" + (" (full-width)" if ct >= 0.99 else "")
    else:
        why = f"face w={cm:.2f}"
    trig = f"{chosen[0]}:{chosen[1]} ({cov:.2f}) — {why}"
    if chosen != ideal:
        trig += f"; widened from {ideal[0]}:{ideal[1]} (hysteresis)"
    return {
        "trigger": trig,
        "C": round(d["C"], 3),
        "c_text": round(ct, 3),
        "text_measured": round(tmeas, 3),
        "c_measured": round(cm, 3),
        "chosen_ar": list(chosen),
        "ideal_ar": list(ideal),
        "coverage": round(cov, 3),
        "hysteresis": chosen != ideal,
        "source": src,
        "layout": layout,
        "n_faces": d["n_faces"],
        "n_persons": d["n_persons"],
        "scene": {
            k: scene.get(k)
            for k in (
                "scene_type",
                "layout",
                "requires_full_width",
                "min_horizontal_coverage",
                "active_subject",
            )
        },
        "faces": d["faces"],
    }


def _split_decision_trace(d, scene) -> dict:
    """'Why this framing' record for a stacked-split segment (no rung)."""
    sep = d["c_meas"]
    return {
        "trigger": f"split (stacked two-shot) — faces {sep:.2f} apart, static dialogue",
        "C": 1.0,
        "c_text": round(d["c_text"], 3),
        "text_measured": round(d.get("text_meas", 0.0), 3),
        "c_measured": round(sep, 3),
        "chosen_ar": None,
        "ideal_ar": None,
        "coverage": 1.0,
        "hysteresis": False,
        "source": "split",
        "layout": "split",
        "n_faces": d["n_faces"],
        "n_persons": d["n_persons"],
        "scene": {
            k: scene.get(k)
            for k in (
                "scene_type",
                "layout",
                "requires_full_width",
                "min_horizontal_coverage",
                "active_subject",
            )
        },
        "faces": d["faces"],
    }


def reconcile(
    scenes: List[dict],
    tracked_frames: List[dict],
    cuts: List[float],
    src_w: int,
    src_h: int,
    duration: float,
    person_frames: Optional[List[dict]] = None,
    rungs: Optional[List[Tuple[int, int]]] = None,
    text_frames: Optional[List[dict]] = None,
) -> List[dict]:
    """Build the per-segment crop plan from cuts + Gemini scenes + detections.

    `rungs` is the output canvas's inner-AR ladder (defaults to the 9:16 RUNGS);
    pass RUNGS_BY_CANVAS["3:4"] to plan onto a 3:4 canvas. `text_frames`
    (text_detect.scan_video_text output) supplies the measured wide-text extent.
    """
    rungs = rungs or RUNGS
    label_map = _global_label_map(tracked_frames)
    scene_starts = [s.get("start_sec", 0.0) for s in scenes]
    bounds = _boundaries(cuts, duration)

    raw: List[dict] = []
    prev_rung: Optional[Tuple[int, int]] = None
    for start, end in bounds:
        scene = _scene_for(scenes, scene_starts, start, end)
        d = _decide_segment(
            scene, tracked_frames, person_frames, start, end, label_map, text_frames
        )
        if d["layout"] == "split":
            # Split fills the canvas with stacked panels — no rung, and it doesn't
            # disturb letterbox hysteresis (prev_rung carries across untouched).
            trace = _split_decision_trace(d, scene)
            inner_ar = None
        else:
            ideal = pick_rung(d["C"], src_w, src_h, None, rungs)
            inner_ar = pick_rung(d["C"], src_w, src_h, prev_rung, rungs)
            prev_rung = inner_ar
            trace = _decision_trace(d, scene, inner_ar, ideal, src_w, src_h)
        raw.append(
            {
                "start": start,
                "end": end,
                "layout": d["layout"],
                "inner_ar": inner_ar,
                "scene_type": scene.get("scene_type", "general"),
                "crops": d["crops"],
                "reason": trace["trigger"],
                "trace": trace,
            }
        )

    merged = _merge_short(raw, MIN_DWELL, rungs)
    for seg in merged:
        _attach_focal_points(seg, tracked_frames, person_frames)
        _fill_keypoints(seg)
    return merged


def attach_keypoints(segments: List[dict], fps: float) -> List[dict]:
    """Smooth each crop's focal series into pan keypoints (per-segment, scene-bounded).

    Pan velocity/deadzone are chosen per segment from its scene_type, so action
    pans fast and dialogue holds steady. Keypoints are in absolute video time;
    the renderer rebases them per segment.
    """
    from focal_path import smooth_focal_path

    for seg in segments:
        start, end = seg["start"], seg["end"]
        dur = max(0.001, end - start)
        max_velocity, deadzone = SCENE_TYPE_PARAMS.get(
            seg.get("scene_type", ""), DEFAULT_SCENE_PARAMS
        )
        for crop in seg["crops"]:
            pts = crop.get("focal_points") or [
                {"time_sec": start, "x": crop.get("x_target", 0.5), "y": 0.5}
            ]
            xs = [p["x"] for p in pts]
            # ~Static subject → center on the median (robust to boundary jitter),
            # rather than a velocity-limited path that can lock off-center.
            if max(xs) - min(xs) <= STATIC_SPREAD:
                cx = statistics.median(xs)
                cy = statistics.median([p.get("y", 0.5) for p in pts])
                crop["keypoints"] = [(start, cx, cy), (end, cx, cy)]
                continue
            local = [
                {
                    "time_sec": max(0.0, min(dur, p["time_sec"] - start)),
                    "x": p["x"],
                    "y": p.get("y", 0.5),
                }
                for p in pts
            ]
            kl = smooth_focal_path(local, [], dur, fps, max_velocity, deadzone)
            crop["keypoints"] = [(t + start, x, y) for (t, x, y) in kl]
    return segments

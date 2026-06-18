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
RUNGS: List[Tuple[int, int]] = [(9, 16), (4, 5), (1, 1), (16, 9)]

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
) -> Tuple[int, int]:
    """Lowest rung whose coverage ≥ required.

    Hysteresis: if the previous rung still covers the content and is at most one
    rung looser than ideal, keep it (avoids single-step flip-flopping). A larger
    gap still tightens so we never stay needlessly letterboxed.

    A small RUNG_TOLERANCE lets a tighter rung win when it *almost* covers the
    requirement — trading a sliver of edge crop for much less letterboxing (e.g.
    a two-shot needing 0.60 takes 1:1 at 0.5625 rather than full 16:9).
    """
    ideal = next(
        (
            r
            for r in RUNGS
            if rung_coverage(r, src_w, src_h) + RUNG_TOLERANCE >= required
        ),
        RUNGS[-1],
    )
    if (
        prev is not None
        and rung_coverage(prev, src_w, src_h) + RUNG_TOLERANCE >= required
    ):
        if 0 <= RUNGS.index(prev) - RUNGS.index(ideal) <= 1:
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


def _decide_segment(scene, tracked_frames, person_frames, start, end, label_map):
    """Decide layout, focal target and required coverage for one segment.

    Falls back to person/body detection when no stable face is present (e.g. a
    subject walking away), then to the Gemini spatial hint.
    """
    stable = _stable_tracks(tracked_frames, start, end)
    c_text = (
        1.0
        if scene.get("requires_full_width")
        else float(scene.get("min_horizontal_coverage") or 0.0)
    )

    # Margin pads the DETECTION-measured width (for tracker slop), not Gemini's
    # stated coverage (which is already a minimum) — avoids double-padding.
    if stable:
        pair = _keep_both_pair(stable, scene)
        if pair:
            a, b = pair
            left = min(a["x"] - a["w"] / 2, b["x"] - b["w"] / 2)
            right = max(a["x"] + a["w"] / 2, b["x"] + b["w"] / 2)
            center = (a["x"] + b["x"]) / 2
            c = max((right - left) + COVERAGE_MARGIN, c_text)
            crop = {"track_id": None, "x_target": center, "source": "center"}
            return {"layout": "keep_both", "crops": [crop], "C": min(1.0, c)}

        tgt = _match_track(stable, scene, label_map)
        c = max(min(tgt["w"], FACE_W_CAP) + COVERAGE_MARGIN, c_text)
        crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": "face"}
        return {"layout": "single", "crops": [crop], "C": min(1.0, c)}

    # No stable face → try person/body detection.
    persons = _segment_persons(person_frames, start, end)
    seg_frames = [f for f in (person_frames or []) if start <= f["time_sec"] <= end]
    frac = len(persons) / max(1, len(seg_frames))
    if persons and frac >= STABLE_FRAC:
        mean_x = sum(p["x"] for p in persons) / len(persons)
        mean_w = sum(p["w"] for p in persons) / len(persons)
        c = max(min(mean_w, PERSON_W_CAP) + COVERAGE_MARGIN, c_text)
        crop = {"track_id": None, "x_target": mean_x, "source": "person"}
        return {"layout": "single", "crops": [crop], "C": min(1.0, c)}

    # Nothing detected → Gemini spatial hint, rely on c_text.
    crop = {"track_id": None, "x_target": _hint_x(scene), "source": "center"}
    return {"layout": "single", "crops": [crop], "C": min(1.0, c_text)}


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


def _merge_short(segments: List[dict], min_dwell: float) -> List[dict]:
    """Collapse identical neighbors and fold sub-dwell segments into the previous one."""
    if not segments:
        return []

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
            prev["end"] = seg["end"]
            if RUNGS.index(seg["inner_ar"]) > RUNGS.index(prev["inner_ar"]):
                prev["inner_ar"] = seg["inner_ar"]
                prev["layout"] = seg["layout"]
                prev["crops"] = seg["crops"]
                prev["reason"] = seg["reason"]
        else:
            out.append(dict(seg))
    return out


def _attach_focal_points(seg, tracked_frames, person_frames):
    """Attach the raw (time, x, y) focal series each crop should follow."""
    start, end = seg["start"], seg["end"]
    for crop in seg["crops"]:
        src = crop.get("source")
        if src == "face":
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


def reconcile(
    scenes: List[dict],
    tracked_frames: List[dict],
    cuts: List[float],
    src_w: int,
    src_h: int,
    duration: float,
    person_frames: Optional[List[dict]] = None,
) -> List[dict]:
    """Build the per-segment crop plan from cuts + Gemini scenes + detections."""
    label_map = _global_label_map(tracked_frames)
    scene_starts = [s.get("start_sec", 0.0) for s in scenes]
    bounds = _boundaries(cuts, duration)

    raw: List[dict] = []
    prev_rung: Optional[Tuple[int, int]] = None
    for start, end in bounds:
        scene = _scene_for(scenes, scene_starts, start, end)
        d = _decide_segment(scene, tracked_frames, person_frames, start, end, label_map)
        rung = pick_rung(d["C"], src_w, src_h, prev_rung)
        prev_rung = rung
        cov = rung_coverage(rung, src_w, src_h)
        raw.append(
            {
                "start": start,
                "end": end,
                "layout": d["layout"],
                "inner_ar": rung,
                "scene_type": scene.get("scene_type", "general"),
                "crops": d["crops"],
                "reason": (
                    f"C={d['C']:.2f} → {rung[0]}:{rung[1]} (covers {cov:.2f}), "
                    f"{d['layout']}, src={d['crops'][0].get('source')}, "
                    f"hint={scene.get('active_subject', 'n/a')}"
                ),
            }
        )

    merged = _merge_short(raw, MIN_DWELL)
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

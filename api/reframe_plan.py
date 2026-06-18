"""Reframe v2 decision layer — turn detections into a per-segment crop plan.

Pure logic: no I/O, no cv2/ffmpeg. Reconciles Gemini scene labels (the *what*)
with MediaPipe face tracks (the *where*) to choose, per scene, an inner aspect
ratio (how much to crop vs. letterbox) and which subject(s) to follow.

Output is a list of SegmentPlan dicts consumed by the renderer:
    {start, end, layout, inner_ar, crops:[{track_id, x_target, keypoints}], reason}
"""

import bisect
from typing import List, Optional, Tuple

# Inner-AR rungs, tightest crop → loosest (most letterbox). Chosen by coverage.
RUNGS: List[Tuple[int, int]] = [(9, 16), (4, 5), (1, 1), (16, 9)]

MIN_DWELL = 2.0  # merge segments shorter than this (seconds)
COVERAGE_MARGIN = 0.04  # safety margin added to required coverage
KEEP_BOTH_SEPARATION = 0.30  # min face-center separation for keep-both
STABLE_FRAC = 0.30  # a track must appear in ≥ this fraction of segment frames


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
    """
    ideal = next(
        (r for r in RUNGS if rung_coverage(r, src_w, src_h) + 1e-9 >= required),
        RUNGS[-1],
    )
    if prev is not None and rung_coverage(prev, src_w, src_h) + 1e-9 >= required:
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
# Per-segment decision
# ---------------------------------------------------------------------------


def _decide_segment(scene, tracked_frames, start, end, label_map):
    """Decide layout, focal target(s) and required coverage for one segment."""
    stable = _stable_tracks(tracked_frames, start, end)
    c_text = (
        1.0
        if scene.get("requires_full_width")
        else float(scene.get("min_horizontal_coverage") or 0.0)
    )

    if not stable:
        crops = [{"track_id": None, "x_target": _hint_x(scene)}]
        return {"layout": "single", "crops": crops, "C": min(1.0, c_text)}

    pair = _keep_both_pair(stable, scene)
    if pair:
        a, b = pair
        left = min(a["x"] - a["w"] / 2, b["x"] - b["w"] / 2)
        right = max(a["x"] + a["w"] / 2, b["x"] + b["w"] / 2)
        c_faces = max(0.0, right - left)
        center = (a["x"] + b["x"]) / 2
        crops = [
            {"track_id": a["track_id"], "x_target": a["x"]},
            {"track_id": b["track_id"], "x_target": b["x"]},
        ]
        c = max(c_faces, c_text) + COVERAGE_MARGIN
        return {
            "layout": "keep_both",
            "crops": crops,
            "C": min(1.0, c),
            "center": center,
        }

    tgt = _match_track(stable, scene, label_map)
    c = max(tgt["w"], c_text) + COVERAGE_MARGIN
    crops = [{"track_id": tgt["track_id"], "x_target": tgt["x"]}]
    return {"layout": "single", "crops": crops, "C": min(1.0, c), "center": tgt["x"]}


# ---------------------------------------------------------------------------
# Segmentation + merging
# ---------------------------------------------------------------------------


def _boundaries(cuts: List[float], duration: float) -> List[Tuple[float, float]]:
    pts = sorted({0.0, duration, *[c for c in cuts if 0.0 < c < duration]})
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


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
    out = [dict(segments[0])]
    for seg in segments[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dwell
        same = seg["inner_ar"] == prev["inner_ar"] and seg["layout"] == prev["layout"]
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


def _fill_keypoints(seg: dict) -> None:
    """Attach static pan keypoints (crop center over the segment) for rendering.

    Phase 1 replaces these with smooth_focal_path output; static centering is
    enough for the diagnostic crop-window overlay and the spike.
    """
    center = seg.pop("_center", 0.5)
    for crop in seg["crops"]:
        x = crop.get("x_target", center)
        crop["keypoints"] = [(seg["start"], x, 0.5), (seg["end"], x, 0.5)]


def reconcile(
    scenes: List[dict],
    tracked_frames: List[dict],
    cuts: List[float],
    src_w: int,
    src_h: int,
    duration: float,
) -> List[dict]:
    """Build the per-segment crop plan from cuts + Gemini scenes + MediaPipe tracks."""
    label_map = _global_label_map(tracked_frames)
    scene_starts = [s.get("start_sec", 0.0) for s in scenes]
    bounds = _boundaries(cuts, duration)

    raw: List[dict] = []
    prev_rung: Optional[Tuple[int, int]] = None
    for start, end in bounds:
        scene = _scene_for(scenes, scene_starts, start, end)
        d = _decide_segment(scene, tracked_frames, start, end, label_map)
        rung = pick_rung(d["C"], src_w, src_h, prev_rung)
        prev_rung = rung
        cov = rung_coverage(rung, src_w, src_h)
        raw.append(
            {
                "start": start,
                "end": end,
                "layout": d["layout"],
                "inner_ar": rung,
                "crops": d["crops"],
                "_center": d.get("center", 0.5),
                "reason": (
                    f"C={d['C']:.2f} → {rung[0]}:{rung[1]} (covers {cov:.2f}), "
                    f"{d['layout']}, subject={scene.get('active_subject', 'n/a')}"
                ),
            }
        )

    merged = _merge_short(raw, MIN_DWELL)
    for seg in merged:
        _fill_keypoints(seg)
    return merged

"""Segment assembly — boundaries, content-aware merging, decision traces.

Turns cut/turn points into cells, folds sub-dwell slices without crossing
content changes, attaches focal series, and builds the observability traces
stored per segment. Pure logic, no I/O.
"""

import math
from typing import List, Optional, Tuple

from reframe_rungs import RUNGS, rung_coverage
from reframe_signals import _segment_persons, _track_series, _window

MIN_DWELL = 2.0  # merge segments shorter than this (seconds)
MAX_SEG_LEN = 5.0  # re-decide framing at least this often, even with no cut
MERGE_X_TOL = 0.08  # only merge same-framing neighbours if the crop center agrees


def _seg_has_face(seg: dict) -> bool:
    """Face/no-face state of a planned segment (from its decision trace).

    A merge or verdict may only ever govern segments that agree on this — a
    speaker shot and a b-roll graphic must never share one framing decision.
    """
    return (seg.get("trace") or {}).get("n_faces", 0) > 0


# Two boundary points closer than this are one boundary (a scene cut and a
# speaker-turn cut landing microseconds apart would otherwise create a
# sub-frame segment — observed as a 0-length cell on rf-udcpl2hd).
BOUNDARY_EPS = 0.1


def _boundaries(cuts: List[float], duration: float) -> List[Tuple[float, float]]:
    """Segment boundaries from cuts, subdivided so no segment exceeds MAX_SEG_LEN.

    Subdivision makes framing robust to missed cuts: a long take (or a stretch
    where cut detection failed) is re-decided every ~MAX_SEG_LEN seconds instead
    of being one stale crop. Identical neighbours are recombined later by merge.
    """
    raw_pts = sorted({0.0, duration, *[c for c in cuts if 0.0 < c < duration]})
    pts = [raw_pts[0]]
    for p in raw_pts[1:]:
        if p - pts[-1] < BOUNDARY_EPS:
            if p == raw_pts[-1]:  # never drop the video end — drop the cut instead
                if len(pts) > 1:
                    pts[-1] = p
                else:
                    pts.append(p)
            continue
        pts.append(p)
    out: List[Tuple[float, float]] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, math.ceil((b - a) / MAX_SEG_LEN))
        step = (b - a) / n
        for k in range(n):
            out.append((a + k * step, b if k == n - 1 else a + (k + 1) * step))
    return out


def _merge_short(
    segments: List[dict],
    min_dwell: float,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> List[dict]:
    """Collapse identical neighbors and fold sub-dwell segments into a neighbor.

    A fold NEVER crosses a content change AT A CUT — a different escalation
    decision (a caption appears, a graphic check) or a face↔no-face transition
    (speaker → b-roll graphic). A cut-bounded sub-dwell cell is a whole short
    SHOT, and an unconditional backward fold would inherit the *previous
    shot's* crop, drop the short shot's own escalation, and let its looser rung
    hijack the survivor's framing (a <2s title card cropped at the previous
    speaker's x). Those fold backward only into a content-compatible previous
    segment, else forward into a content-compatible next one, else stay
    standalone — a 1.5s title card is better rendered on its own framing than
    mis-framed.

    A MID-SHOT sub-dwell cell (its boundary is a subdivision or speaker-turn
    re-cut, not a real cut) is different: a "content change" there is detector
    noise — a face the detector dropped for a beat, observed on rf-udcpl2hd —
    so it bridges into its own shot unconditionally.
    """
    if not segments:
        return []
    rungs = rungs or RUNGS

    def _cx(s):
        return s["crops"][0].get("x_target", 0.5)

    def _esc_sig(s):
        # Merge signature for an escalation: no_subject merges by KIND alone (adjacent
        # no-detection cells are the same graphic/shot), so a long graphic doesn't
        # fragment; text/subject merge only when the exact content key matches.
        e = s.get("escalate")
        if not e:
            return None
        k = e.get("kind")
        return k if k == "no_subject" else (k, e.get("key"))

    def _compatible(a, b):
        # Content compatibility: one Gemini verdict / one framing decision may
        # only ever govern segments that agree on these.
        return _esc_sig(a) == _esc_sig(b) and _seg_has_face(a) == _seg_has_face(b)

    def _looser(a, b):
        # True when a's rung letterboxes more than b's. Split (inner_ar=None)
        # has no rung index, so it never swaps in/out here (its strict dwell
        # gate already keeps it from being sub-dwell).
        both_runged = isinstance(a["inner_ar"], tuple) and isinstance(
            b["inner_ar"], tuple
        )
        return both_runged and rungs.index(a["inner_ar"]) > rungs.index(b["inner_ar"])

    out = [dict(segments[0])]
    for seg in segments[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dwell
        prev_short = (prev["end"] - prev["start"]) < min_dwell
        # Folding across the prev|seg boundary is allowed when the content
        # matches, or when that boundary isn't a real cut (same shot — any
        # apparent content change in a sub-dwell slice there is detector noise).
        bridge = _compatible(seg, prev) or not seg.get("starts_at_cut", True)
        # Same framing AND the crop is on the same spot — otherwise keep separate
        # so each subdivided cell re-frames its own subject (don't smear a pan
        # across two different subjects).
        same = (
            _compatible(seg, prev)
            and seg["inner_ar"] == prev["inner_ar"]
            and seg["layout"] == prev["layout"]
            and abs(_cx(seg) - _cx(prev)) <= MERGE_X_TOL
        )
        if same or (too_short and bridge):
            # Extend prev; keep the looser rung so we never crop out the short bit.
            prev["end"] = seg["end"]
            # Carry a merged-in segment's escalation if the survivor had none, so
            # an ambiguity in the folded slice still reaches Gemini.
            if seg.get("escalate") and not prev.get("escalate"):
                prev["escalate"] = seg["escalate"]
            if _looser(seg, prev):
                prev["inner_ar"] = seg["inner_ar"]
                prev["layout"] = seg["layout"]
                prev["crops"] = seg["crops"]
                prev["reason"] = seg["reason"]
                prev["trace"] = seg.get("trace")
        elif prev_short and bridge:
            # The previous slice was sub-dwell but couldn't fold backward (a
            # content change at a cut); fold it forward into this segment
            # instead. The longer segment keeps its framing — only the rung
            # widens if the short slice needed a looser one.
            merged = dict(seg)
            merged["start"] = prev["start"]
            merged["starts_at_cut"] = prev.get("starts_at_cut", False)
            if prev.get("escalate") and not merged.get("escalate"):
                merged["escalate"] = prev["escalate"]
            if _looser(prev, merged):
                merged["inner_ar"] = prev["inner_ar"]
            out[-1] = merged
        else:
            out.append(dict(seg))
    return out


def _attach_focal_points(seg, tracked_frames, track_times, person_frames, person_times):
    """Attach the raw (time, x, y) focal series each crop should follow.

    Windows the (post-merge) segment once via bisect, then reads each crop's track
    or person series from that slice.
    """
    start, end = seg["start"], seg["end"]
    tf_win = _window(tracked_frames, track_times, start, end)
    pf_win = _window(person_frames, person_times, start, end)
    for crop in seg["crops"]:
        src = crop.get("source")
        if src in ("face", "speaker", "split_top", "split_bottom"):
            pts = _track_series(tf_win, crop["track_id"])
        elif src == "person":
            pts = [
                {"time_sec": p["time_sec"], "x": p["x"], "y": p["y"]}
                for p in _segment_persons(pf_win)
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
    """Structured 'why this framing' record + one-line trigger (observability).

    Pass 1 letterboxes only from CPU subject geometry, so the trigger explains
    framing in those terms (two-face span, active speaker, person body, face
    width). A TEXT/graphic letterbox is a Pass-2 (gemini) verdict applied later in
    `reframe_decide.apply_verdicts`, which overwrites `trigger`/`source` itself.
    """
    cov = rung_coverage(chosen, src_w, src_h)
    cm = d["c_meas"]
    tmeas = d.get("text_meas", 0.0)
    src, layout = d["source"], d["layout"]
    if layout == "keep_both":
        why = f"two faces span {cm:.2f}"
    elif src == "speaker":
        why = "active speaker (mouth movement)"
    elif src == "person":
        why = f"no face; person body w={cm:.2f}"
    elif d["n_faces"] == 0:
        why = "no detection"
    else:
        why = f"face w={cm:.2f}"
    trig = f"{chosen[0]}:{chosen[1]} ({cov:.2f}) — {why}"
    if chosen != ideal:
        trig += f"; widened from {ideal[0]}:{ideal[1]} (rung DP: bar stability)"
    return {
        "trigger": trig,
        "C": round(d["C"], 3),
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

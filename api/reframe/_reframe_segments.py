"""Segment assembly — boundaries, content-aware merging, decision traces.

Turns cut/turn points into cells, folds sub-dwell slices without crossing
content changes, attaches focal series, and builds the observability traces
stored per segment. Pure logic, no I/O.
"""

import math
from typing import Any, List, Optional, Tuple

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
    """Segment boundaries from cuts, subdivided so no segment exceeds MAX_SEG_LEN."""
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


def _esc_sig(s: dict) -> Any:
    e = s.get("escalate")
    if not e:
        return None
    k = e.get("kind")
    return k if k == "no_subject" else (k, e.get("key"))


def _compatible(a: dict, b: dict) -> bool:
    return _esc_sig(a) == _esc_sig(b) and _seg_has_face(a) == _seg_has_face(b)


def _looser(a: dict, b: dict, rung_idx: dict) -> bool:
    both_runged = isinstance(a["inner_ar"], tuple) and isinstance(b["inner_ar"], tuple)
    return both_runged and rung_idx[a["inner_ar"]] > rung_idx[b["inner_ar"]]


def _extend_prev_seg(prev: dict, seg: dict, rung_idx: dict) -> None:
    prev["end"] = seg["end"]
    if seg.get("escalate") and not prev.get("escalate"):
        prev["escalate"] = seg["escalate"]
    if _looser(seg, prev, rung_idx):
        for k in ("inner_ar", "layout", "crops", "reason"):
            prev[k] = seg[k]
        prev["trace"] = seg.get("trace")


def _merge_short(
    segments: List[dict],
    min_dwell: float,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> List[dict]:
    """Collapse identical neighbors and fold sub-dwell segments into a neighbor."""
    if not segments:
        return []
    rungs = rungs or RUNGS
    rung_idx = {r: i for i, r in enumerate(rungs)}
    out = [dict(segments[0])]
    for seg in segments[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dwell
        prev_short = (prev["end"] - prev["start"]) < min_dwell
        compat = _compatible(seg, prev)
        bridge = compat or not seg.get("starts_at_cut", True)
        cx_diff = abs(
            seg["crops"][0].get("x_target", 0.5) - prev["crops"][0].get("x_target", 0.5)
        )
        same = (
            compat
            and seg["inner_ar"] == prev["inner_ar"]
            and seg["layout"] == prev["layout"]
            and cx_diff <= MERGE_X_TOL
        )
        if same or (too_short and bridge):
            _extend_prev_seg(prev, seg, rung_idx)
        elif prev_short and bridge:
            merged = {
                **seg,
                "start": prev["start"],
                "starts_at_cut": prev.get("starts_at_cut", False),
            }
            if prev.get("escalate") and not merged.get("escalate"):
                merged["escalate"] = prev["escalate"]
            if _looser(prev, merged, rung_idx):
                merged["inner_ar"] = prev["inner_ar"]
            out[-1] = merged
        else:
            out.append(dict(seg))
    return out


def _attach_focal_points(
    seg: dict,
    tracked_frames: List[dict],
    track_times: List[float],
    person_frames: List[dict],
    person_times: List[float],
) -> None:
    """Attach the raw (time, x, y) focal series each crop should follow."""
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
                for p in _segment_persons(pf_win, tf_win, hint_x=crop.get("x_target"))
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


_SCENE_TRACE_KEYS = (
    "scene_type",
    "layout",
    "requires_full_width",
    "min_horizontal_coverage",
    "active_subject",
)


def _decision_why(d: dict) -> str:
    cm = d["c_meas"]
    src, layout = d["source"], d["layout"]
    if src == "semantic_graphic":
        why = "semantic: full-frame graphic/slide/title"
    elif layout == "keep_both":
        why = f"two faces span {cm:.2f}"
    elif src == "speaker":
        why = "active speaker (mouth movement)"
    elif src == "person":
        why = f"no face; person body w={cm:.2f}"
    elif d["n_faces"] == 0:
        why = "no detection"
    else:
        why = f"face w={cm:.2f}"
    if d.get("text_keep"):
        tk = d["text_keep"]
        why += f"; semantic: keep text band [{tk[0]:.2f}, {tk[1]:.2f}]"
    return why


def _decision_trace(
    d: dict,
    scene: dict,
    chosen: Tuple[int, int],
    ideal: Tuple[int, int],
    src_w: int,
    src_h: int,
) -> dict:
    """Structured 'why this framing' record + one-line trigger (observability)."""
    cov = rung_coverage(chosen, src_w, src_h)
    trig = f"{chosen[0]}:{chosen[1]} ({cov:.2f}) — {_decision_why(d)}"
    if chosen != ideal:
        trig += f"; widened from {ideal[0]}:{ideal[1]} (rung DP: bar stability)"
    return {
        "trigger": trig,
        "C": round(d["C"], 3),
        "text_measured": round(d.get("text_meas", 0.0), 3),
        "c_measured": round(d["c_meas"], 3),
        "chosen_ar": list(chosen),
        "ideal_ar": list(ideal),
        "coverage": round(cov, 3),
        "hysteresis": chosen != ideal,
        "source": d["source"],
        "layout": d["layout"],
        "text_keep": d.get("text_keep"),
        "n_faces": d["n_faces"],
        "n_persons": d["n_persons"],
        "scene": {k: scene.get(k) for k in _SCENE_TRACE_KEYS},
        "faces": d["faces"],
    }


def _split_decision_trace(d: dict, scene: dict) -> dict:
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
        "scene": {k: scene.get(k) for k in _SCENE_TRACE_KEYS},
        "faces": d["faces"],
    }

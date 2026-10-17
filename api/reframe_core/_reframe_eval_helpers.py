"""Helper functions and constants for reframe_eval reference-free quality metrics."""

import bisect
import math
import statistics
from typing import Any, List, Optional, Tuple

from reframe_filters import crop_geometry, crop_left_px_at, split_panel_geometry
from reframe_plan import COVERAGE_MARGIN, SPEAKER_MIN_ACTIVITY

FACE_CUT = (0.05, 0.15)
OVER_LETTERBOX = (0.15, 0.35)
SPEAKER_MISS = (0.10, 0.25)
CENTER_OFFSET = (0.12, 0.25)
CONTAINMENT = (0.90, 0.75)
AV_SYNC = (0.30, 0.10)
FRAMED_ACTIVE = (0.60, 0.40)

EDGE_EPS = 0.005
JUMP_FRAC = 0.15
JUMP_MIN_SEC = 0.25
ACTIVITY_HI = SPEAKER_MIN_ACTIVITY
SPEAKER_WINDOW_SEC = 2.0
FACE_CUT_MIN_W = 0.08
FACE_CUT_MARGIN = 0.03
MIN_DIALOGUE_FRAMES = 8
_WORST_KEEP = 3
_RANK = {"na": 0, "ok": 0, "warn": 1, "fail": 2}


def _seg_at(plan: List[dict], starts: List[float], t: float) -> Optional[dict]:
    """The segment whose [start, end) window contains t (held to last)."""
    if not plan:
        return None
    i = bisect.bisect_right(starts, t) - 1
    i = max(0, min(i, len(plan) - 1))
    return plan[i]


def _window_from(
    crop_w: int, max_x: int, src_w: int, kps: Optional[list], t: float
) -> Tuple[float, float]:
    """Normalized [left, right] of one rendered crop window at time t."""
    if crop_w <= 0 or max_x <= 0:
        return 0.0, 1.0
    left_px = crop_left_px_at(kps or [], src_w, crop_w, max_x, t)
    return left_px / src_w, (left_px + crop_w) / src_w


def _crop_window(seg: dict, src_w: int, src_h: int, t: float) -> Tuple[float, float]:
    """Normalized [left, right] of the rendered crop window at time t (crop 0)."""
    crop_w, _fg_h, max_x = crop_geometry(tuple(seg["inner_ar"]), src_w, src_h)
    kps = seg["crops"][0].get("keypoints") if seg.get("crops") else None
    return _window_from(crop_w, max_x, src_w, kps, t)


def _crop_windows(
    seg: dict, src_w: int, src_h: int, t: float, canvas_h: int
) -> List[Tuple[float, float]]:
    """Normalized [left, right] of every rendered crop window at time t."""
    crops = seg.get("crops") or []
    if seg.get("layout") == "split" and len(crops) == 2:
        crop_w, _ph, max_x = split_panel_geometry(src_w, src_h, 1080, canvas_h)
        return [
            _window_from(crop_w, max_x, src_w, crop.get("keypoints"), t)
            for crop in crops
        ]
    return [_crop_window(seg, src_w, src_h, t)]


def _subject_bucket_mismatch(seg: dict, src_w: int, src_h: int, canvas_h: int) -> bool:
    """True when a person/center crop entirely excludes the semantic subject's third."""
    trace = seg.get("trace") or {}
    if trace.get("source") not in ("person", "center"):
        return False
    bucket = ((trace.get("scene") or {}).get("active_subject") or "").lower()
    if bucket not in ("left", "center", "right"):
        return False
    b0 = {"left": 0.0, "center": 1 / 3.0, "right": 2 / 3.0}[bucket]
    t_mid = (seg["start"] + seg["end"]) / 2.0
    windows = _crop_windows(seg, src_w, src_h, t_mid, canvas_h)
    return bool(windows) and all(
        min(right, b0 + 1 / 3.0) - max(left, b0) <= 0 for left, right in windows
    )


def _flag(
    value: Optional[float], warn: float, fail: float, higher_is_better: bool
) -> str:
    if value is None:
        return "na"
    if higher_is_better:
        if value <= fail:
            return "fail"
        return "warn" if value <= warn else "ok"
    if value >= fail:
        return "fail"
    return "warn" if value >= warn else "ok"


def _rollup(*flags: str) -> str:
    return max(flags, key=lambda f: _RANK.get(f, 0)) if flags else "na"


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0 or sy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _track_in(frame: dict, tid: Any) -> Optional[dict]:
    for tr in frame.get("tracks", []):
        if tr.get("track_id") == tid:
            return tr
    return None


def _normalize_speech(speech_intervals: Any) -> List[Tuple[float, float]]:
    """Coerce Chirp turns ({start_sec,end_sec}) or (start,end) tuples → intervals."""
    out: List[Tuple[float, float]] = []
    for s in speech_intervals or []:
        if isinstance(s, dict):
            a, b = s.get("start_sec"), s.get("end_sec")
        else:
            a, b = s[0], s[1]
        if a is not None and b is not None and b > a:
            out.append((float(a), float(b)))
    return sorted(out)


def _speech_at(intervals: List[Tuple[float, float]], t: float) -> bool:
    return any(a <= t <= b for a, b in intervals)


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 3)


def _build_mar_series(tracked_frames: List[dict]) -> dict:
    mar_series: dict = {}
    for fr in tracked_frames:
        for tr in fr.get("tracks", []):
            if tr.get("mouth") is not None:
                ts, ms = mar_series.setdefault(tr["track_id"], ([], []))
                ts.append(fr["time_sec"])
                ms.append(tr["mouth"])
    for tid, (ts, ms) in mar_series.items():
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        mar_series[tid] = ([ts[i] for i in order], [ms[i] for i in order])
    return mar_series


def _track_activity(mar_series: dict, tr: Optional[dict], t: float) -> float:
    if tr is None or tr.get("mouth") is None:
        return 0.0
    ser = mar_series.get(tr["track_id"])
    if not ser or len(ser[1]) < 2:
        return 0.0
    times, mouths = ser
    lo = bisect.bisect_left(times, t - SPEAKER_WINDOW_SEC)
    hi = bisect.bisect_right(times, t + SPEAKER_WINDOW_SEC)
    win = mouths[lo:hi]
    return statistics.pstdev(win) if len(win) >= 2 else 0.0


def _track_span_need(seg: dict, tracked_frames: List[dict]) -> float:
    ids = [c["track_id"] for c in seg.get("crops", []) if c.get("track_id") is not None]
    if not ids:
        return float(seg.get("trace", {}).get("C") or 0.0)
    span = 0.0
    for fr in tracked_frames:
        if not (seg["start"] <= fr["time_sec"] <= seg["end"]):
            continue
        xs = [
            (tr["x"] - tr["w"] / 2, tr["x"] + tr["w"] / 2)
            for tr in fr.get("tracks", [])
            if tr.get("track_id") in ids
        ]
        if xs:
            span = max(span, max(r for _, r in xs) - min(left for left, _ in xs))
    return min(1.0, span + COVERAGE_MARGIN) if span else 0.0


def _must_keep_width(seg: dict, tracked_frames: List[dict]) -> float:
    """Horizontal coverage this segment can actually justify."""
    need = _track_span_need(seg, tracked_frames)
    esc = seg.get("escalate") or {}
    verdict = esc.get("verdict") or {}
    crops = seg.get("crops") or []
    cx = crops[0].get("x_target", 0.5) if crops else 0.5
    if verdict.get("action") == "letterbox":
        band = (esc.get("facts") or {}).get("band")
        if band:
            req = 2.0 * max(cx - float(band[0]), float(band[1]) - cx)
            need = max(need, min(1.0, req + COVERAGE_MARGIN))
        else:
            cov = verdict.get("coverage") or (esc.get("facts") or {}).get(
                "text_coverage"
            )
            if cov:
                need = max(need, min(1.0, float(cov)))
    tk = (seg.get("trace") or {}).get("text_keep")
    if tk:
        req = 2.0 * max(cx - float(tk[0]), float(tk[1]) - cx)
        need = max(need, min(1.0, req + COVERAGE_MARGIN))
    return need


def _new_accum() -> dict:
    return {
        "face_frames": 0,
        "cut_frames": 0,
        "subj_frames": 0,
        "subj_contained": 0,
        "center_offsets": [],
        "av_framed": [],
        "av_speech": [],
        "dialogue_frames": 0,
        "active_frames": 0,
        "speech_dialogue": 0,
        "miss_frames": 0,
        "worst_cut": [],
        "worst_miss": [],
    }


def _eval_frame_face_cut(
    tracks: List[dict],
    framed_tids: List[Any],
    framed_present: List[dict],
    windows: List[Tuple[float, float]],
    t: float,
    acc: dict,
) -> None:
    framed_w = max((tr["w"] for tr in framed_present), default=0.0)
    important = [
        tr
        for tr in tracks
        if tr["w"] >= FACE_CUT_MIN_W
        and tr.get("track_id") not in framed_tids
        and tr["w"] >= framed_w - FACE_CUT_MARGIN
    ]
    if not (tracks and (framed_present or important)):
        return
    acc["face_frames"] += 1
    over = 0.0
    culprit = None
    for tr in important:
        fl, frt = tr["x"] - tr["w"] / 2, tr["x"] + tr["w"] / 2
        clip = min(max(left - fl, frt - right, 0.0) for (left, right) in windows)
        if clip > over:
            over, culprit = clip, tr
    if over > EDGE_EPS and culprit is not None:
        acc["cut_frames"] += 1
        lbl = culprit.get("track_id", "?")
        acc["worst_cut"].append(
            (over, t, f"face {lbl} (w={culprit['w']:.2f}) clipped {over:.0%}")
        )


def _eval_frame_containment(
    fr: dict, crops: List[dict], windows: List[Tuple[float, float]], acc: dict
) -> None:
    for ci, crop in enumerate(crops):
        tid = crop.get("track_id")
        if tid is None:
            continue
        tr = _track_in(fr, tid)
        if tr is None:
            continue
        left, right = windows[ci]
        acc["subj_frames"] += 1
        fl, frt = tr["x"] - tr["w"] / 2, tr["x"] + tr["w"] / 2
        if fl >= left - EDGE_EPS and frt <= right + EDGE_EPS:
            acc["subj_contained"] += 1
        if (right - left) < 1.0 - EDGE_EPS:
            acc["center_offsets"].append(abs(tr["x"] - (left + right) / 2.0))


def _eval_frame_dialogue(
    tracks: List[dict],
    framed_tids: List[Any],
    framed_present: List[dict],
    windows: List[Tuple[float, float]],
    t: float,
    mar_series: dict,
    speech: List[Tuple[float, float]],
    acc: dict,
) -> None:
    mouthed = [tr for tr in tracks if tr.get("mouth") is not None]
    if len(mouthed) < 2:
        return
    acc["dialogue_frames"] += 1
    fa = max((_track_activity(mar_series, tr, t) for tr in framed_present), default=0.0)
    if fa > ACTIVITY_HI:
        acc["active_frames"] += 1
    speaking = _speech_at(speech, t)
    if speech:
        acc["av_framed"].append(fa)
        acc["av_speech"].append(1.0 if speaking else 0.0)
    if not speaking:
        return
    acc["speech_dialogue"] += 1
    for tr in mouthed:
        if tr.get("track_id") in framed_tids:
            continue
        a = _track_activity(mar_series, tr, t)
        off = not any(
            left - EDGE_EPS <= tr["x"] <= right + EDGE_EPS for (left, right) in windows
        )
        if off and a > ACTIVITY_HI and a > fa:
            acc["miss_frames"] += 1
            acc["worst_miss"].append(
                (a, t, f"off-frame face {tr.get('track_id')} talking")
            )
            break


def _accumulate_frames(
    tracked_frames: List[dict],
    plan: List[dict],
    starts: List[float],
    src_w: int,
    src_h: int,
    canvas_h: int,
    mar_series: dict,
    speech: List[Tuple[float, float]],
) -> dict:
    acc = _new_accum()
    for fr in tracked_frames:
        t = fr["time_sec"]
        seg = _seg_at(plan, starts, t)
        if seg is None:
            continue
        windows = _crop_windows(seg, src_w, src_h, t, canvas_h)
        tracks = fr.get("tracks", [])
        crops = seg.get("crops") or []
        framed_tids = [
            c.get("track_id") for c in crops if c.get("track_id") is not None
        ]
        for c in crops:
            framed_tids.extend(c.get("track_ids") or [])
        framed_present = [tr for tr in tracks if tr.get("track_id") in framed_tids]
        _eval_frame_face_cut(tracks, framed_tids, framed_present, windows, t, acc)
        _eval_frame_containment(fr, crops, windows, acc)
        _eval_frame_dialogue(
            tracks, framed_tids, framed_present, windows, t, mar_series, speech, acc
        )
    return acc

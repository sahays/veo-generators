"""Reframe v2 reference-free eval — a per-run quality report card.

Pure logic: no I/O, no cv2/ffmpeg. Scores the chosen crop plan against signals
that did NOT decide the framing — *all* detections (incl. faces we cut) and the
audio (Chirp speech turns) — so the report can falsify the framing rather than
rubber-stamp it. See docs/reframing-eval.md.

The renderer always crops the full source height (only width/x vary — see
``reframe_filters.crop_geometry``), so a subject can only be cut *horizontally*;
letterbox bars come from the rung's ``fg_h < 1920``. Every metric is geometry
over plan + detections + speech intervals — no output re-decode.

Metrics are proxies bounded by detector quality (a missed face can't be scored
as cut) and audio cleanliness (av-sync degrades with music / off-screen
narration / overlapping speakers). Treat the report as a tripwire + tuning
scoreboard, not a grade.
"""

import bisect
import math
import statistics
from typing import List, Optional, Tuple

from reframe_filters import crop_geometry, crop_left_px_at, split_panel_geometry
from reframe_plan import COVERAGE_MARGIN, RUNGS, SPEAKER_MIN_ACTIVITY, rung_coverage

# --- Flag thresholds (warn, fail). Tunable scoreboard knobs. -----------------
# "Lower is better" metrics: value ≥ warn → warn, ≥ fail → fail.
FACE_CUT = (0.05, 0.15)
OVER_LETTERBOX = (0.15, 0.35)
SPEAKER_MISS = (0.10, 0.25)
CENTER_OFFSET = (0.12, 0.25)  # framed face-x distance from crop center (frac src width)
# "Higher is better" metrics: value ≤ warn → warn, ≤ fail → fail.
CONTAINMENT = (0.90, 0.75)
AV_SYNC = (0.30, 0.10)
FRAMED_ACTIVE = (0.60, 0.40)

EDGE_EPS = 0.005  # ignore sub-half-percent clipping (rounding noise)
JUMP_FRAC = 0.15  # adjacent-keypoint x jump above this = a crop jump
ACTIVITY_HI = SPEAKER_MIN_ACTIVITY  # windowed MAR stdev above this = "talking"
# Local mouth-movement is measured over a TIME radius, not a sample COUNT: detection
# sampling rate varies (sample_fps) and a face can appear intermittently, so a fixed
# ±N-samples window would span an unpredictable number of seconds (and silently scale
# with fps). ±2s mirrors the old ±2-samples-at-1fps intent but stays correct at any
# rate / with gaps in the track.
SPEAKER_WINDOW_SEC = 2.0  # ± seconds of MAR samples for local mouth-movement
# A clipped face only counts as a real cut when it (a) clears a minimum size
# (not a stray background detection) and (b) is at least as prominent as the
# subject we actually framed — i.e. we cut someone who mattered as much as who
# we kept, or we kept no face at all. Cutting a clearly-smaller face is the
# expected cost of single-subject framing, not a failure.
FACE_CUT_MIN_W = 0.08
FACE_CUT_MARGIN = 0.03
# Talker metrics need enough multi-face samples to mean anything; below this the
# block is null (a handful of frames is noise, not a verdict).
MIN_DIALOGUE_FRAMES = 8
_WORST_KEEP = 3  # worst-offending timestamps kept per failing metric
_RANK = {"na": 0, "ok": 0, "warn": 1, "fail": 2}


def _seg_at(plan: List[dict], starts: List[float], t: float) -> Optional[dict]:
    """The segment whose [start, end) window contains t (held to last)."""
    if not plan:
        return None
    i = bisect.bisect_right(starts, t) - 1
    i = max(0, min(i, len(plan) - 1))
    return plan[i]


def _window_from(crop_w, max_x, src_w, kps, t) -> Tuple[float, float]:
    """Normalized [left, right] of one rendered crop window at time t, via the
    shared `crop_left_px_at` model (so it can't drift from the FFmpeg filter)."""
    if crop_w <= 0 or max_x <= 0:
        return 0.0, 1.0  # crop keeps the full width → nothing cut horizontally
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
    """Normalized [left, right] of every rendered crop window at time t.

    One window for single/keep_both (the inner-AR crop); one per panel for a
    stacked split. Uses the shared `crop_left_px_at` model so cut/containment
    reasoning matches exactly what the filter renders.
    """
    crops = seg.get("crops") or []
    if seg.get("layout") == "split" and len(crops) == 2:
        crop_w, _ph, max_x = split_panel_geometry(src_w, src_h, 1080, canvas_h)
        return [
            _window_from(crop_w, max_x, src_w, crop.get("keypoints"), t)
            for crop in crops
        ]
    return [_crop_window(seg, src_w, src_h, t)]


def _flag(value, warn, fail, higher_is_better: bool) -> str:
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
    if sx <= 0 or sy <= 0:  # a constant series → correlation undefined
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(sx * sy)


def _pct(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def _track_in(frame: dict, tid) -> Optional[dict]:
    for tr in frame.get("tracks", []):
        if tr.get("track_id") == tid:
            return tr
    return None


def _normalize_speech(speech_intervals) -> List[Tuple[float, float]]:
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


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def evaluate(
    plan: List[dict],
    tracked_frames: List[dict],
    person_frames: Optional[List[dict]],
    speech_intervals,
    src_w: int,
    src_h: int,
    duration: float,
    sample_fps: float = 1.0,
    canvas_h: int = 1920,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> dict:
    """Reference-free per-run report card for a reframe plan.

    Returns ``{}`` for an empty plan. The ``talker`` block is ``null`` when no
    multi-face MAR data exists; its audio-dependent metrics are ``null`` when
    there are no speech intervals. See module docstring for the metric set.
    """
    if not plan:
        return {}

    rungs = rungs or RUNGS
    starts = [s["start"] for s in plan]
    minutes = max(duration, 0.001) / 60.0
    speech = _normalize_speech(speech_intervals)

    # Per-track MAR time series → per-frame "talking" = local mouth movement
    # (stdev of MAR over a small window), the per-frame analogue of the plan's
    # segment-level speaking variance. A still mouth (open or closed) scores ~0.
    mar_series: dict = {}  # tid -> ([times], [mouths]) sorted by time
    for fr in tracked_frames:
        for tr in fr.get("tracks", []):
            if tr.get("mouth") is not None:
                ts, ms = mar_series.setdefault(tr["track_id"], ([], []))
                ts.append(fr["time_sec"])
                ms.append(tr["mouth"])
    for tid, (ts, ms) in mar_series.items():
        order = sorted(range(len(ts)), key=lambda i: ts[i])
        mar_series[tid] = ([ts[i] for i in order], [ms[i] for i in order])

    def activity(tr: Optional[dict], t: float) -> float:
        if tr is None or tr.get("mouth") is None:
            return 0.0
        ser = mar_series.get(tr["track_id"])
        if not ser or len(ser[1]) < 2:
            return 0.0
        times, mouths = ser
        # Samples within ±SPEAKER_WINDOW_SEC of t (time-based, fps-independent).
        lo = bisect.bisect_left(times, t - SPEAKER_WINDOW_SEC)
        hi = bisect.bisect_right(times, t + SPEAKER_WINDOW_SEC)
        win = mouths[lo:hi]
        return statistics.pstdev(win) if len(win) >= 2 else 0.0

    # --- Per-frame accumulators ---------------------------------------------
    face_frames = cut_frames = 0
    subj_frames = subj_contained = 0
    center_offsets: List[float] = []
    av_framed: List[float] = []
    av_speech: List[float] = []
    dialogue_frames = active_frames = 0
    speech_dialogue = miss_frames = 0
    worst_cut: List[Tuple[float, float, str]] = []  # (overage, t, detail)
    worst_miss: List[Tuple[float, float, str]] = []

    for fr in tracked_frames:
        t = fr["time_sec"]
        seg = _seg_at(plan, starts, t)
        if seg is None:
            continue
        windows = _crop_windows(seg, src_w, src_h, t, canvas_h)
        tracks = fr.get("tracks", [])
        crops = seg.get("crops") or []

        # The subjects we framed — one per crop (two for a split). "In frame" means
        # inside *any* panel, so a split shows both and cuts neither.
        framed_tids = [
            c.get("track_id") for c in crops if c.get("track_id") is not None
        ]
        framed_present = [tr for tr in tracks if tr.get("track_id") in framed_tids]
        framed_w = max((tr["w"] for tr in framed_present), default=0.0)

        # Goal 1: are we cutting a face that *mattered*? Count a clipped face only
        # when it is not one we framed, clears a min size, and is at least as
        # prominent as the largest subject we kept (or we kept none). A clearly
        # smaller background face outside the crop is the expected cost of
        # single-subject framing, not a failure. For a split, a clip is the *least*
        # clipping across panels (a face shown in either panel isn't cut).
        important = [
            tr
            for tr in tracks
            if tr["w"] >= FACE_CUT_MIN_W
            and tr.get("track_id") not in framed_tids
            and tr["w"] >= framed_w - FACE_CUT_MARGIN
        ]
        if tracks and (framed_present or important):
            face_frames += 1
            over = 0.0
            culprit = None
            for tr in important:
                fl, frt = tr["x"] - tr["w"] / 2, tr["x"] + tr["w"] / 2
                clip = min(
                    max(left - fl, frt - right, 0.0) for (left, right) in windows
                )
                if clip > over:
                    over, culprit = clip, tr
            if over > EDGE_EPS:
                cut_frames += 1
                lbl = culprit.get("track_id") if culprit else "?"
                worst_cut.append(
                    (over, t, f"face {lbl} (w={culprit['w']:.2f}) clipped {over:.0%}")
                )

        # Containment + centering: each framed subject within its own panel/crop.
        for ci, crop in enumerate(crops):
            tid = crop.get("track_id")
            if tid is None:
                continue
            tr = _track_in(fr, tid)
            if tr is None:
                continue
            left, right = windows[ci]
            subj_frames += 1
            fl, frt = tr["x"] - tr["w"] / 2, tr["x"] + tr["w"] / 2
            if fl >= left - EDGE_EPS and frt <= right + EDGE_EPS:
                subj_contained += 1
            center_offsets.append(abs(tr["x"] - (left + right) / 2.0))

        # Goal 2: talker metrics over dialogue (multi-face MAR) frames.
        mouthed = [tr for tr in tracks if tr.get("mouth") is not None]
        if len(mouthed) >= 2:
            dialogue_frames += 1
            # Whoever we framed is "active" if any framed panel shows a moving
            # mouth — a split frames both, so it tracks the talker by construction.
            fa = max((activity(tr, t) for tr in framed_present), default=0.0)
            if fa > ACTIVITY_HI:
                active_frames += 1
            speaking = _speech_at(speech, t)
            if speech:
                av_framed.append(fa)
                av_speech.append(1.0 if speaking else 0.0)
            if speaking:
                speech_dialogue += 1
                # Wrong-face: an off-frame face (outside every panel) out-talks
                # whoever we framed.
                for tr in mouthed:
                    if tr.get("track_id") in framed_tids:
                        continue
                    a = activity(tr, t)
                    off = not any(
                        left - EDGE_EPS <= tr["x"] <= right + EDGE_EPS
                        for (left, right) in windows
                    )
                    if off and a > ACTIVITY_HI and a > fa:
                        miss_frames += 1
                        worst_miss.append(
                            (a, t, f"off-frame face {tr.get('track_id')} talking")
                        )
                        break

    # --- Aggregate: letterbox / framing -------------------------------------
    face_cut_rate = (cut_frames / face_frames) if face_frames else 0.0
    subject_containment = (subj_contained / subj_frames) if subj_frames else None

    mean_lb = 0.0
    lb_segments = 0
    over_lb_hits = 0
    seg_reports: List[dict] = []
    for seg in plan:
        # A split fills the canvas with stacked panels — no letterbox bars, no rung.
        if seg.get("layout") == "split" or seg.get("inner_ar") is None:
            seg_reports.append(
                {
                    "start": round(seg["start"], 2),
                    "end": round(seg["end"], 2),
                    "inner_ar": None,
                    "letterbox_pct": 0.0,
                    "over_letterbox": False,
                    "reason": seg.get("reason", ""),
                }
            )
            continue
        _cw, fg_h, _mx = crop_geometry(tuple(seg["inner_ar"]), src_w, src_h)
        lb = max(0.0, 1.0 - fg_h / canvas_h)
        dur = max(0.0, seg["end"] - seg["start"])
        mean_lb += lb * dur
        over = False
        if lb > 0:  # this segment is letterboxed
            lb_segments += 1
            # A Gemini-confirmed text letterbox is INTENTIONAL — the bars preserve
            # on-screen text/graphics the subject-width geometry can't see, so it is
            # never "over". over_letterbox_rate stays a measure of *needless*
            # (unexplained) letterboxing, which is the regression it was built for.
            verdict = (seg.get("escalate") or {}).get("verdict") or {}
            gemini_text = (seg.get("trace") or {}).get(
                "source"
            ) == "gemini_text" or verdict.get("action") == "letterbox"
            if not gemini_text:
                need = _must_keep_width(seg, tracked_frames)
                idx = (
                    rungs.index(tuple(seg["inner_ar"]))
                    if tuple(seg["inner_ar"]) in rungs
                    else -1
                )
                if idx > 0 and rung_coverage(rungs[idx - 1], src_w, src_h) >= need:
                    over = True
                    over_lb_hits += 1
        seg_reports.append(
            {
                "start": round(seg["start"], 2),
                "end": round(seg["end"], 2),
                "inner_ar": list(seg["inner_ar"]),
                "letterbox_pct": round(lb, 3),
                "over_letterbox": over,
                "reason": seg.get("reason", ""),
            }
        )
    mean_letterbox_pct = mean_lb / max(duration, 0.001)
    over_letterbox_rate = (over_lb_hits / lb_segments) if lb_segments else 0.0

    letterbox = {
        "face_cut_rate": round(face_cut_rate, 3),
        "subject_containment": _r(subject_containment),
        "over_letterbox_rate": round(over_letterbox_rate, 3),
        "mean_letterbox_pct": round(mean_letterbox_pct, 3),
    }
    letterbox["flag"] = _rollup(
        _flag(face_cut_rate, *FACE_CUT, higher_is_better=False),
        _flag(over_letterbox_rate, *OVER_LETTERBOX, higher_is_better=False),
        _flag(subject_containment, *CONTAINMENT, higher_is_better=True),
    )

    # --- Aggregate: talker ---------------------------------------------------
    talker = None
    if dialogue_frames >= MIN_DIALOGUE_FRAMES:
        av_sync = _pearson(av_framed, av_speech) if av_framed else None
        framed_active_rate = active_frames / dialogue_frames
        speaker_miss_rate = miss_frames / speech_dialogue if speech_dialogue else None
        talker = {
            "av_sync_score": _r(av_sync),
            "framed_speaker_active_rate": round(framed_active_rate, 3),
            "speaker_miss_rate": _r(speaker_miss_rate),
            "dialogue_frames": dialogue_frames,
        }
        talker["flag"] = _rollup(
            _flag(av_sync, *AV_SYNC, higher_is_better=True),
            _flag(framed_active_rate, *FRAMED_ACTIVE, higher_is_better=True),
            _flag(speaker_miss_rate, *SPEAKER_MISS, higher_is_better=False),
        )

    # --- Aggregate: stability ------------------------------------------------
    def _ar_key(s):
        ar = s.get("inner_ar")
        return tuple(ar) if ar else None  # split (None) is its own key

    ar_changes = sum(1 for a, b in zip(plan, plan[1:]) if _ar_key(a) != _ar_key(b))
    crop_jumps = 0
    for seg in plan:
        kps = seg["crops"][0].get("keypoints", []) if seg.get("crops") else []
        for (_, x0, _), (_, x1, _) in zip(kps, kps[1:]):
            if abs(x1 - x0) > JUMP_FRAC:
                crop_jumps += 1
    stability = {
        "ar_changes_per_min": round(ar_changes / minutes, 2),
        "crop_jumps_per_min": round(crop_jumps / minutes, 2),
        "center_offset_p50": round(_pct(center_offsets, 0.5), 3),
        "center_offset_p90": round(_pct(center_offsets, 0.9), 3),
    }
    stability["flag"] = _flag(
        _pct(center_offsets, 0.9) if center_offsets else None,
        *CENTER_OFFSET,
        higher_is_better=False,
    )

    # --- Worst offenders -----------------------------------------------------
    worst: List[dict] = []
    for over, t, detail in sorted(worst_cut, reverse=True)[:_WORST_KEEP]:
        worst.append({"t": round(t, 2), "metric": "face_cut_rate", "detail": detail})
    for a, t, detail in sorted(worst_miss, reverse=True)[:_WORST_KEEP]:
        worst.append(
            {"t": round(t, 2), "metric": "speaker_miss_rate", "detail": detail}
        )
    for sr in seg_reports:
        if sr["over_letterbox"]:
            worst.append(
                {
                    "t": sr["start"],
                    "metric": "over_letterbox_rate",
                    "detail": f"{sr['inner_ar']} but a tighter rung fit — {sr['reason']}",
                }
            )
    worst = worst[: _WORST_KEEP * 3]

    overall = _rollup(
        letterbox["flag"], stability["flag"], (talker or {}).get("flag", "na")
    )

    return {
        "letterbox": letterbox,
        "talker": talker,
        "stability": stability,
        "segments": seg_reports,
        "worst": worst,
        "overall": overall,
        "meta": {
            "duration": round(duration, 2),
            "segments": len(plan),
            "sampled_frames": len(tracked_frames),
            "has_speech": bool(speech),
            "note": "reference-free proxies; tripwire + tuning scoreboard, not a grade",
        },
    }


def _must_keep_width(seg: dict, tracked_frames: List[dict]) -> float:
    """Horizontal coverage the framed subject(s) actually need in this segment.

    Measured from detections (independent of the rung the plan picked): the
    widest left→right span of the followed track(s) across the segment's frames,
    padded by COVERAGE_MARGIN. Falls back to the plan's required coverage
    (``trace.C``) when the crop follows no specific track (center/person).
    """
    ids = [c["track_id"] for c in seg.get("crops", []) if c.get("track_id") is not None]
    if not ids:
        # No followed track (center/person crop) — trust the plan's own required
        # coverage; if absent, claim nothing (0 → never flagged over-letterbox).
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


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 3)

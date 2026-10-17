"""Reframe v2 reference-free eval — a per-run quality report card.

Pure logic: no I/O, no cv2/ffmpeg. Scores the chosen crop plan against signals
that did NOT decide the framing — *all* detections (incl. faces we cut) and the
audio (Chirp speech turns) — so the report can falsify the framing rather than
rubber-stamp it. See docs/reframing-eval.md.
"""

from typing import Any, List, Optional, Tuple

from reframe_eval_helpers import (  # noqa: F401
    ACTIVITY_HI,
    AV_SYNC,
    CENTER_OFFSET,
    CONTAINMENT,
    EDGE_EPS,
    FACE_CUT,
    FACE_CUT_MARGIN,
    FACE_CUT_MIN_W,
    FRAMED_ACTIVE,
    JUMP_FRAC,
    JUMP_MIN_SEC,
    MIN_DIALOGUE_FRAMES,
    OVER_LETTERBOX,
    SPEAKER_MISS,
    SPEAKER_WINDOW_SEC,
    _RANK,
    _WORST_KEEP,
    _accumulate_frames,
    _build_mar_series,
    _crop_window,
    _crop_windows,
    _eval_frame_containment,
    _eval_frame_dialogue,
    _eval_frame_face_cut,
    _flag,
    _must_keep_width,
    _new_accum,
    _normalize_speech,
    _pct,
    _pearson,
    _r,
    _rollup,
    _seg_at,
    _speech_at,
    _subject_bucket_mismatch,
    _track_activity,
    _track_in,
    _window_from,
)
from reframe_filters import crop_geometry
from reframe_plan import COVERAGE_MARGIN, RUNGS, SPEAKER_MIN_ACTIVITY, rung_coverage  # noqa: F401


def _eval_single_segment(
    seg: dict,
    tracked_frames: List[dict],
    src_w: int,
    src_h: int,
    canvas_h: int,
    rungs: List[Tuple[int, int]],
    rung_idx: dict,
) -> Tuple[dict, float, bool, bool, bool]:
    if seg.get("layout") == "split" or seg.get("inner_ar") is None:
        rep = {
            "start": round(seg["start"], 2),
            "end": round(seg["end"], 2),
            "inner_ar": None,
            "letterbox_pct": 0.0,
            "over_letterbox": False,
            "reason": seg.get("reason", ""),
        }
        return rep, 0.0, False, False, False
    mismatch = _subject_bucket_mismatch(seg, src_w, src_h, canvas_h)
    _cw, fg_h, _mx = crop_geometry(tuple(seg["inner_ar"]), src_w, src_h)
    lb = max(0.0, 1.0 - fg_h / canvas_h)
    dur = max(0.0, seg["end"] - seg["start"])
    over = False
    is_lb = lb > 0
    if is_lb:
        need = _must_keep_width(seg, tracked_frames)
        idx = rung_idx.get(tuple(seg["inner_ar"]), -1)
        if idx > 0 and rung_coverage(rungs[idx - 1], src_w, src_h) >= need:
            over = True
    rep = {
        "start": round(seg["start"], 2),
        "end": round(seg["end"], 2),
        "inner_ar": list(seg["inner_ar"]),
        "letterbox_pct": round(lb, 3),
        "over_letterbox": over,
        "reason": seg.get("reason", ""),
        **({"subject_mismatch": True} if mismatch else {}),
    }
    return rep, lb * dur, is_lb, over, mismatch


def _eval_segments_and_letterbox(
    plan: List[dict],
    tracked_frames: List[dict],
    src_w: int,
    src_h: int,
    canvas_h: int,
    duration: float,
    rungs: List[Tuple[int, int]],
    rung_idx: dict,
    acc: dict,
) -> Tuple[dict, List[dict], int]:
    face_cut_rate = (
        (acc["cut_frames"] / acc["face_frames"]) if acc["face_frames"] else 0.0
    )
    subject_containment = (
        (acc["subj_contained"] / acc["subj_frames"]) if acc["subj_frames"] else None
    )
    mean_lb = 0.0
    lb_segments = over_lb_hits = subj_mismatch = 0
    seg_reports: List[dict] = []
    for seg in plan:
        rep, lb_dur, is_lb, over, mismatch = _eval_single_segment(
            seg, tracked_frames, src_w, src_h, canvas_h, rungs, rung_idx
        )
        seg_reports.append(rep)
        mean_lb += lb_dur
        lb_segments += int(is_lb)
        over_lb_hits += int(over)
        subj_mismatch += int(mismatch)
    mean_letterbox_pct = mean_lb / max(duration, 0.001)
    over_letterbox_rate = (over_lb_hits / lb_segments) if lb_segments else 0.0
    letterbox = {
        "face_cut_rate": round(face_cut_rate, 3),
        "subject_containment": _r(subject_containment),
        "over_letterbox_rate": round(over_letterbox_rate, 3),
        "mean_letterbox_pct": round(mean_letterbox_pct, 3),
        "flag": _rollup(
            _flag(face_cut_rate, *FACE_CUT, higher_is_better=False),
            _flag(over_letterbox_rate, *OVER_LETTERBOX, higher_is_better=False),
            _flag(subject_containment, *CONTAINMENT, higher_is_better=True),
        ),
    }
    return letterbox, seg_reports, subj_mismatch


def _build_talker_block(acc: dict) -> Optional[dict]:
    dialogue_frames = acc["dialogue_frames"]
    if dialogue_frames < MIN_DIALOGUE_FRAMES:
        return None
    av_sync = _pearson(acc["av_framed"], acc["av_speech"]) if acc["av_framed"] else None
    framed_active_rate = acc["active_frames"] / dialogue_frames
    speaker_miss_rate = (
        acc["miss_frames"] / acc["speech_dialogue"] if acc["speech_dialogue"] else None
    )
    return {
        "av_sync_score": _r(av_sync),
        "framed_speaker_active_rate": round(framed_active_rate, 3),
        "speaker_miss_rate": _r(speaker_miss_rate),
        "dialogue_frames": dialogue_frames,
        "flag": _rollup(
            _flag(av_sync, *AV_SYNC, higher_is_better=True),
            _flag(framed_active_rate, *FRAMED_ACTIVE, higher_is_better=True),
            _flag(speaker_miss_rate, *SPEAKER_MISS, higher_is_better=False),
        ),
    }


def _build_stability_block(
    plan: List[dict], minutes: float, center_offsets: List[float]
) -> dict:
    ar_changes = sum(
        1
        for a, b in zip(plan, plan[1:])
        if (tuple(a["inner_ar"]) if a.get("inner_ar") else None)
        != (tuple(b["inner_ar"]) if b.get("inner_ar") else None)
    )
    crop_jumps = 0
    prev_last_x = None
    for seg in plan:
        kps = seg["crops"][0].get("keypoints", []) if seg.get("crops") else []
        if kps and prev_last_x is not None and not seg.get("starts_at_cut", True):
            if abs(kps[0][1] - prev_last_x) > JUMP_FRAC:
                crop_jumps += 1
        for (t0, x0, _), (t1, x1, _) in zip(kps, kps[1:]):
            if abs(x1 - x0) > JUMP_FRAC and (t1 - t0) < JUMP_MIN_SEC:
                crop_jumps += 1
        prev_last_x = kps[-1][1] if kps else None
    return {
        "ar_changes_per_min": round(ar_changes / minutes, 2),
        "crop_jumps_per_min": round(crop_jumps / minutes, 2),
        "center_offset_p50": round(_pct(center_offsets, 0.5), 3),
        "center_offset_p90": round(_pct(center_offsets, 0.9), 3),
        "flag": _flag(
            _pct(center_offsets, 0.9) if center_offsets else None,
            *CENTER_OFFSET,
            higher_is_better=False,
        ),
    }


def _build_worst_offenders(acc: dict, seg_reports: List[dict]) -> List[dict]:
    worst: List[dict] = []
    for _over, t, detail in sorted(acc["worst_cut"], reverse=True)[:_WORST_KEEP]:
        worst.append({"t": round(t, 2), "metric": "face_cut_rate", "detail": detail})
    for _a, t, detail in sorted(acc["worst_miss"], reverse=True)[:_WORST_KEEP]:
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
    return worst[: _WORST_KEEP * 3]


def _build_perception_block(
    perception: Optional[dict], tracked_frames: List[dict]
) -> Optional[dict]:
    if perception is None:
        return None
    sampled = len(tracked_frames)
    expected = perception.get("frames_expected")
    faces_per_frame = (
        sum(len(f.get("tracks", [])) for f in tracked_frames) / sampled
        if sampled
        else 0.0
    )
    if perception.get("face_backend") == "haar" or sampled == 0:
        pflag = "fail"
    elif expected and sampled < 0.5 * expected:
        pflag = "warn"
    else:
        pflag = "ok"
    return {
        **perception,
        "frames_sampled": sampled,
        "faces_per_frame": round(faces_per_frame, 2),
        "flag": pflag,
    }


def _build_failing_metrics(
    letterbox: dict,
    center_offsets: List[float],
    talker: Optional[dict],
    perception_block: Optional[dict],
    subj_mismatch: int,
) -> List[dict]:
    checks: List[Tuple[str, Optional[float], Tuple[float, float], bool]] = [
        ("face_cut_rate", letterbox["face_cut_rate"], FACE_CUT, False),
        (
            "over_letterbox_rate",
            letterbox["over_letterbox_rate"],
            OVER_LETTERBOX,
            False,
        ),
        ("subject_containment", letterbox["subject_containment"], CONTAINMENT, True),
        (
            "center_offset_p90",
            _pct(center_offsets, 0.9) if center_offsets else None,
            CENTER_OFFSET,
            False,
        ),
    ]
    if talker:
        checks += [
            ("av_sync_score", talker["av_sync_score"], AV_SYNC, True),
            (
                "framed_speaker_active_rate",
                talker["framed_speaker_active_rate"],
                FRAMED_ACTIVE,
                True,
            ),
            ("speaker_miss_rate", talker["speaker_miss_rate"], SPEAKER_MISS, False),
        ]
    failing = [
        {"metric": name, "value": _r(value), "flag": f, "warn": warn, "fail": fail}
        for name, value, (warn, fail), higher in checks
        for f in [_flag(value, warn, fail, higher_is_better=higher)]
        if f in ("warn", "fail")
    ]
    if perception_block and perception_block["flag"] != "ok":
        failing.append(
            {
                "metric": "perception",
                "value": perception_block.get("face_backend"),
                "flag": perception_block["flag"],
                "warn": None,
                "fail": None,
            }
        )
    if subj_mismatch:
        failing.append(
            {
                "metric": "subject_mismatch_segments",
                "value": subj_mismatch,
                "flag": "warn",
                "warn": None,
                "fail": None,
            }
        )
    return failing


def _build_meta_block(
    plan: List[dict],
    tracked_frames: List[dict],
    duration: float,
    speech: List[Tuple[float, float]],
    subj_mismatch: int,
) -> dict:
    return {
        "duration": round(duration, 2),
        "segments": len(plan),
        "sampled_frames": len(tracked_frames),
        "has_speech": bool(speech),
        "center_crop_segments": sum(
            1
            for s in plan
            if (s.get("trace") or {}).get("source") == "center"
            and not (s.get("trace") or {}).get("n_faces")
        ),
        "speaker_segments": sum(
            1 for s in plan if (s.get("trace") or {}).get("source") == "speaker"
        ),
        "letterbox_16x9_segments": sum(
            1 for s in plan if s.get("inner_ar") and tuple(s["inner_ar"]) == (16, 9)
        ),
        "split_segments": sum(1 for s in plan if s.get("layout") == "split"),
        "subject_mismatch_segments": subj_mismatch,
        "note": "reference-free proxies; tripwire + tuning scoreboard, not a grade",
    }


def evaluate(
    plan: List[dict],
    tracked_frames: List[dict],
    person_frames: Optional[List[dict]],
    speech_intervals: Any,
    src_w: int,
    src_h: int,
    duration: float,
    sample_fps: float = 1.0,
    canvas_h: int = 1920,
    rungs: Optional[List[Tuple[int, int]]] = None,
    perception: Optional[dict] = None,
) -> dict:
    """Reference-free per-run report card for a reframe plan."""
    if not plan:
        return {}
    rungs = rungs or RUNGS
    rung_idx = {r: i for i, r in enumerate(rungs)}
    starts = [s["start"] for s in plan]
    minutes = max(duration, 0.001) / 60.0
    speech = _normalize_speech(speech_intervals)
    mar_series = _build_mar_series(tracked_frames)
    acc = _accumulate_frames(
        tracked_frames, plan, starts, src_w, src_h, canvas_h, mar_series, speech
    )
    letterbox, seg_reports, subj_mismatch = _eval_segments_and_letterbox(
        plan, tracked_frames, src_w, src_h, canvas_h, duration, rungs, rung_idx, acc
    )
    talker = _build_talker_block(acc)
    stability = _build_stability_block(plan, minutes, acc["center_offsets"])
    worst = _build_worst_offenders(acc, seg_reports)
    perception_block = _build_perception_block(perception, tracked_frames)
    overall = _rollup(
        letterbox["flag"],
        stability["flag"],
        (talker or {}).get("flag", "na"),
        (perception_block or {}).get("flag", "na"),
    )
    failing = _build_failing_metrics(
        letterbox, acc["center_offsets"], talker, perception_block, subj_mismatch
    )
    report: dict = {
        "letterbox": letterbox,
        "talker": talker,
        "stability": stability,
        "segments": seg_reports,
        "worst": worst,
        "overall": overall,
        "failing": failing,
        "meta": _build_meta_block(
            plan, tracked_frames, duration, speech, subj_mismatch
        ),
    }
    if perception_block is not None:
        report["perception"] = perception_block
    return report

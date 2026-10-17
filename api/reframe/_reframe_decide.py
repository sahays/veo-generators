"""Pass 2 — apply gemini-3.5-flash verdicts to the deterministic plan.

Pass 1 (`reframe_plan` + `reframe_escalation`) emits clustered, batched decision
points, each with a deterministic *fallback*. This module turns the model's
verdicts back into concrete plan edits, and provides the prompt/thumbnail
plumbing the Gemini call needs. Keeping it separate keeps `apply_verdicts` pure
and unit-testable; the actual model call lives in `gemini_service`.

A `text_presence` verdict of `letterbox` re-pulls the segment's rung to keep the
side text in frame; `crop` (or a missing/dropped verdict) leaves the fallback —
follow the speaker — untouched. Other decision kinds will plug in here as they
are wired.
"""

import logging
from typing import List, Optional, Tuple

from reframe_decide_helpers import (  # noqa: F401
    THUMBS_PER_CLUSTER,
    _DECISION_INTRO_TMPL,
    _cluster_sample_secs,
    _extend_letterbox_walk,
    _harmonize_sandwich,
    _overlay_subjects,
    _overlay_text,
    _pick_candidate_by_side,
    _render_cluster_thumbs,
    _widen_neighbor,
    build_cluster_block,
    build_decision_intro,
)
from reframe_plan import (
    COVERAGE_MARGIN,
    RUNGS,
    _group_crop,
    _seg_has_face,  # noqa: F401
    pick_rung,
    rung_coverage,
)

logger = logging.getLogger(__name__)

DECISION_SCHEMA = "reframe-decisions-schema"


def render_decision_thumbs(
    video_path: str, clusters: List[dict], active_area: Optional[dict] = None
) -> dict:
    """{cluster key → [annotated JPEG bytes]} — several representative frames."""
    try:
        import cv2
    except Exception:
        logger.warning(
            "reframe_decide: cv2 unavailable — no thumbnails",
            extra={
                "who": "reframe_decide",
                "where": "render_decision_thumbs",
                "what": "cv2 unavailable",
                "why": "ImportError",
                "how": "return empty dict",
            },
        )
        return {}
    from reframe_active_area import slice_frame

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(
            f"reframe_decide: cannot open {video_path}",
            extra={
                "who": "reframe_decide",
                "where": "render_decision_thumbs",
                "what": "cannot open video",
                "why": video_path,
                "how": "return empty dict",
            },
        )
        return {}
    try:
        return {
            c["key"]: _render_cluster_thumbs(cap, c, active_area, cv2, slice_frame)
            for c in clusters
        }
    finally:
        cap.release()


_LETTERBOX_KINDS = (
    "text_presence",
    "no_subject",
    "weak_subject",
    "active_speaker",
    "subject_choice",
)


def _apply_letterbox_verdict(
    seg: dict,
    esc: dict,
    v: dict,
    src_w: int,
    src_h: int,
    ladder: List[Tuple[int, int]],
    ladder_idx: dict,
) -> bool:
    kind = esc["kind"]
    cov = float(v.get("coverage") or esc["facts"].get("text_coverage") or 1.0)
    band = esc["facts"].get("band")
    if band and seg.get("crops"):
        cx = seg["crops"][0].get("x_target", 0.5)
        cov = max(
            cov, 2.0 * max(cx - float(band[0]), float(band[1]) - cx) + COVERAGE_MARGIN
        )
    new_ar = pick_rung(min(1.0, cov), src_w, src_h, ladder)
    cur = tuple(seg["inner_ar"]) if seg.get("inner_ar") else None
    if cur in ladder_idx:
        new_ar = ladder[
            min(max(ladder_idx[new_ar], ladder_idx[cur] + 1), len(ladder) - 1)
        ]
    if new_ar == cur:
        return False
    if seg.get("layout") == "split":
        seg["layout"] = "single"
        seg["crops"] = [{"track_id": None, "x_target": 0.5, "source": "center"}]
    seg["inner_ar"] = new_ar
    label = "side text" if kind == "text_presence" else "full-frame graphic"
    seg["reason"] = f"gemini: letterbox for {label} (cov {cov:.2f})"
    trace = seg.get("trace")
    if trace:
        trace.update(
            {
                "chosen_ar": list(new_ar),
                "coverage": round(rung_coverage(new_ar, src_w, src_h), 3),
                "trigger": seg["reason"],
                "layout": seg["layout"],
                "source": "gemini_text"
                if kind == "text_presence"
                else "gemini_graphic",
            }
        )
    return True


def _apply_single_verdict(
    seg: dict,
    vmap: dict,
    src_w: int,
    src_h: int,
    ladder: List[Tuple[int, int]],
    ladder_idx: dict,
    tracked_frames: Optional[List[dict]],
    track_times: List[float],
    person_frames: Optional[List[dict]],
    person_times: List[float],
) -> bool:
    esc = seg.get("escalate")
    if not esc:
        return False
    v = vmap.get(esc.get("cluster_key") or esc["key"])
    if not v:
        return False
    seg["escalate"] = {**esc, "verdict": v}
    kind = esc["kind"]
    if kind in _LETTERBOX_KINDS and v.get("action") == "letterbox":
        return _apply_letterbox_verdict(seg, esc, v, src_w, src_h, ladder, ladder_idx)
    if kind == "active_speaker" and v.get("action") in ("keep_both", "split"):
        return _apply_keep_both(
            seg,
            v["action"],
            src_w,
            src_h,
            ladder,
            tracked_frames,
            track_times,
            person_frames,
            person_times,
        )
    if kind in ("subject_choice", "active_speaker") and v.get("subject"):
        return _apply_subject(
            seg,
            v["subject"],
            tracked_frames,
            track_times,
            person_frames,
            person_times,
            kind,
        )
    return False


def apply_verdicts(
    segments: List[dict],
    verdicts: Optional[List[dict]],
    src_w: int,
    src_h: int,
    rungs: Optional[List[Tuple[int, int]]],
    tracked_frames: Optional[List[dict]] = None,
    person_frames: Optional[List[dict]] = None,
) -> int:
    """Edit the plan in place from the model's verdicts. Returns # segments changed."""
    vmap = {v.get("key"): v for v in (verdicts or []) if v.get("key")}
    track_times = [f["time_sec"] for f in tracked_frames] if tracked_frames else []
    person_times = [f["time_sec"] for f in person_frames] if person_frames else []
    ladder = rungs or RUNGS
    ladder_idx = {r: i for i, r in enumerate(ladder)}
    return sum(
        1
        for seg in segments
        if _apply_single_verdict(
            seg,
            vmap,
            src_w,
            src_h,
            ladder,
            ladder_idx,
            tracked_frames,
            track_times,
            person_frames,
            person_times,
        )
    )


def _set_keep_both_layout(
    seg: dict,
    action: str,
    a: dict,
    b: dict,
    facts: dict,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
) -> str:
    if action == "split" and facts.get("can_split"):
        seg["layout"] = "split"
        seg["inner_ar"] = None
        seg["crops"] = [
            {"track_id": a["track_id"], "x_target": a["x"], "source": "split_top"},
            {"track_id": b["track_id"], "x_target": b["x"], "source": "split_bottom"},
        ]
        seg["reason"] = "gemini: split two-person dialogue"
        return "gemini_split"
    crop, span = _group_crop([a, b])
    seg["layout"] = "keep_both"
    seg["inner_ar"] = pick_rung(min(1.0, span + COVERAGE_MARGIN), src_w, src_h, rungs)
    seg["crops"] = [crop]
    seg["reason"] = "gemini: keep both speakers"
    return "gemini_keep_both"


def _apply_keep_both(
    seg: dict,
    action: str,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
    tracked_frames: Optional[List[dict]],
    track_times: List[float],
    person_frames: Optional[List[dict]],
    person_times: List[float],
) -> bool:
    """Convert a speaker-escalated segment to keep_both (or split) per Gemini."""
    facts = (seg.get("escalate") or {}).get("facts") or {}
    cands = facts.get("candidates") or []
    pair_ids = facts.get("pair") or []
    pair = [c for c in cands if c["track_id"] in pair_ids]
    if len(pair) != 2:
        pair = sorted(cands, key=lambda c: -(c.get("frac") or 0.0))[:2]
    if len(pair) < 2:
        return False
    a, b = sorted(pair, key=lambda c: c["x"])
    src = _set_keep_both_layout(seg, action, a, b, facts, src_w, src_h, rungs)
    trace = seg.get("trace")
    if trace:
        trace.update(
            {
                "trigger": seg["reason"],
                "source": src,
                "layout": seg["layout"],
                "chosen_ar": list(seg["inner_ar"]) if seg["inner_ar"] else None,
            }
        )
    if tracked_frames is not None:
        from reframe_plan import _attach_focal_points

        _attach_focal_points(
            seg, tracked_frames, track_times, person_frames or [], person_times or []
        )
    return True


def harmonize_letterbox(
    segments: List[dict],
    src_w: int,
    src_h: int,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> int:
    """Extend a Pass-2 TEXT letterbox across same-shot neighbors. Returns # widened."""
    ladder = rungs or RUNGS
    ladder_idx = {r: i for i, r in enumerate(ladder)}
    changed = 0
    for i, seg in enumerate(segments):
        if (seg.get("trace") or {}).get("source") != "gemini_text" or not seg.get(
            "inner_ar"
        ):
            continue
        target = tuple(seg["inner_ar"])
        if target not in ladder:
            continue
        reason = f"{seg.get('reason', 'gemini: letterbox')} (extended across shot)"
        changed += _extend_letterbox_walk(
            segments, i, 1, seg, target, reason, ladder_idx, src_w, src_h
        )
        changed += _extend_letterbox_walk(
            segments, i, -1, seg, target, reason, ladder_idx, src_w, src_h
        )
    return changed + _harmonize_sandwich(segments, ladder, ladder_idx, src_w, src_h)


def _apply_subject(
    seg: dict,
    side: str,
    tracked_frames: Optional[List[dict]],
    track_times: List[float],
    person_frames: Optional[List[dict]],
    person_times: List[float],
    kind: str = "subject_choice",
) -> bool:
    """Re-target a segment's crop to the Gemini-chosen person; refresh its focal
    series so the pan follows the new track. Returns True if the subject changed.

    `kind` distinguishes a "who is the subject" pick (subject_choice) from a "who is
    speaking, center them" pick (active_speaker) for the label/source stamp."""
    cands = (seg.get("escalate", {}).get("facts") or {}).get("candidates") or []
    if not cands:
        return False
    chosen = _pick_candidate_by_side(cands, side)
    crop = seg["crops"][0]
    if crop.get("track_id") == chosen["track_id"]:
        return False
    is_speaker = kind == "active_speaker"
    crop.update(
        {
            "track_id": chosen["track_id"],
            "x_target": chosen["x"],
            "source": "speaker" if is_speaker else "face",
        }
    )
    seg["reason"] = (
        f"gemini: center {side} speaker"
        if is_speaker
        else f"gemini: follow {side} subject"
    )
    if seg.get("trace"):
        seg["trace"]["trigger"] = seg["reason"]
        seg["trace"]["source"] = "gemini_speaker" if is_speaker else "gemini_subject"
    if tracked_frames is not None:
        from reframe_plan import _attach_focal_points

        _attach_focal_points(
            seg, tracked_frames, track_times, person_frames or [], person_times or []
        )
    return True

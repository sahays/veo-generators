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

import json
import logging
from typing import List

from reframe_plan import pick_rung, rung_coverage

logger = logging.getLogger(__name__)

DECISION_SCHEMA = "reframe-decisions-schema"

THUMBS_PER_CLUSTER = 3  # frames sampled across a segment so a verdict isn't from 1

DECISION_INTRO = (
    "You are the decision engine for a 16:9 → 9:16 (portrait) video reframer. "
    "Deterministic CV handles geometry; you resolve only what needs human-like "
    "judgment from the pixels. Each decision point below gives its `key`, a "
    "question, and SEVERAL thumbnail frames sampled across that shot. The frames "
    "are ANNOTATED to show what a tight portrait crop would do:\n"
    "  • the GREEN box = the region the crop keeps; the DARKENED area = what gets "
    "cut off.\n"
    "  • for subject choices, vertical lines mark each candidate person, labeled "
    "left / center / right.\n"
    "Answer each point by echoing its exact `key` and an `action`.\n"
    "TEXT decisions (key 'text:…') — look at the DARKENED (cut) area across the "
    "frames:\n"
    "  • letterbox — readable on-screen text or a graphic (caption, title, lower-"
    "third, chart/table, map, UI, logo) sits in the cut area and would be lost; "
    "also give `coverage` = fraction of width (0-1) to keep so it stays visible.\n"
    "  • crop — the cut area is only background: scenery, a building, landscape, "
    "plants, a wall, blur, or out-of-focus decor. A PERSON in front of a busy "
    "background is crop, NOT letterbox. Judge only by readable text/graphics you "
    "actually see.\n"
    "SUBJECT decisions (key 'subject:…'): action=follow and `subject` = left | "
    "center | right — the one person to track (whoever is speaking / the focus).\n"
    "Return exactly one verdict per key."
)


def build_cluster_block(cluster: dict) -> str:
    """The text describing one decision point (its annotated frames follow)."""
    return (
        f"\n[key={cluster['key']}] {cluster['question']}\n"
        f"facts: {json.dumps(cluster['facts'])}\n"
        "(annotated frames for this key follow)"
    )


def _overlay_text(frame, crop_keeps):
    """Darken what a tight crop cuts; green-box what it keeps — so Gemini SEES it."""
    import cv2

    h, w = frame.shape[:2]
    wl, wr = int(crop_keeps[0] * w), int(crop_keeps[1] * w)
    dim = frame.copy()
    cv2.rectangle(dim, (0, 0), (wl, h), (0, 0, 0), -1)
    cv2.rectangle(dim, (wr, 0), (w, h), (0, 0, 0), -1)
    frame = cv2.addWeighted(dim, 0.55, frame, 0.45, 0)
    cv2.rectangle(frame, (wl, 1), (wr, h - 2), (0, 200, 0), 2)
    return frame


def _overlay_subjects(frame, candidates):
    """Mark each candidate person with a labeled vertical line."""
    import cv2

    h, w = frame.shape[:2]
    for c in candidates:
        x = int(c["x"] * w)
        cv2.line(frame, (x, 0), (x, h), (0, 180, 255), 2)
        cv2.putText(
            frame,
            c.get("pos", ""),
            (max(2, x - 28), 26),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 180, 255),
            2,
        )
    return frame


def render_decision_thumbs(video_path: str, clusters: List[dict]) -> dict:
    """{cluster key → [annotated JPEG bytes]} — several frames across each shot.

    Samples THUMBS_PER_CLUSTER frames spread over each cluster's [start, end] and
    draws the crop keep/cut overlay (text) or candidate markers (subject), so the
    model judges from what the crop actually does, not from numbers. Best-effort:
    degrades to {} if cv2 is unavailable; skips frames that can't be read.
    """
    try:
        import cv2
    except Exception:
        logger.warning("reframe_decide: cv2 unavailable — no thumbnails")
        return {}
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"reframe_decide: cannot open {video_path}")
        return {}
    out: dict = {}
    try:
        for c in clusters:
            s, e = c["start"], c["end"]
            fracs = (0.2, 0.5, 0.8)[:THUMBS_PER_CLUSTER]
            secs = [s + (e - s) * f for f in fracs] if e > s else [s]
            facts = c.get("facts") or {}
            imgs: List[bytes] = []
            for t in secs:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                if c["kind"] == "text_presence" and facts.get("crop_keeps"):
                    frame = _overlay_text(frame, facts["crop_keeps"])
                elif c["kind"] == "subject_choice" and facts.get("candidates"):
                    frame = _overlay_subjects(frame, facts["candidates"])
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    imgs.append(buf.tobytes())
            out[c["key"]] = imgs
    finally:
        cap.release()
    return out


def apply_verdicts(
    segments,
    verdicts,
    src_w,
    src_h,
    rungs,
    tracked_frames=None,
    person_frames=None,
) -> int:
    """Edit the plan in place from the model's verdicts. Returns # segments changed.

    Matches each escalated segment to its verdict by `key`:
    - `text_presence` + `letterbox` → re-pull the rung to the verdict coverage
      (keep the side text); `crop` / missing verdict keeps the deterministic crop.
    - `subject_choice` + `follow` → re-target the crop to the chosen person and
      re-derive its focal series (needs `tracked_frames`); missing verdict keeps
      the deterministic pick.
    The verdict is stamped onto `seg["escalate"]["verdict"]` for the trace.
    """
    vmap = {v.get("key"): v for v in (verdicts or []) if v.get("key")}
    track_times = [f["time_sec"] for f in tracked_frames] if tracked_frames else []
    person_times = [f["time_sec"] for f in person_frames] if person_frames else []
    changed = 0
    for seg in segments:
        esc = seg.get("escalate")
        if not esc:
            continue
        v = vmap.get(esc["key"])
        if not v:
            continue  # no verdict (dropped over budget / call failed) → fallback
        seg["escalate"] = {**esc, "verdict": v}
        kind = esc["kind"]
        if kind == "text_presence" and v.get("action") == "letterbox":
            cov = float(v.get("coverage") or esc["facts"].get("text_coverage") or 1.0)
            new_ar = pick_rung(min(1.0, cov), src_w, src_h, None, rungs)
            if new_ar != seg.get("inner_ar"):
                seg["inner_ar"] = new_ar
                seg["reason"] = f"gemini: letterbox for side text (cov {cov:.2f})"
                trace = seg.get("trace")
                if trace:
                    trace["chosen_ar"] = list(new_ar)
                    trace["coverage"] = round(rung_coverage(new_ar, src_w, src_h), 3)
                    trace["trigger"] = seg["reason"]
                    trace["source"] = "gemini_text"
                changed += 1
        elif kind == "subject_choice" and v.get("subject"):
            if _apply_subject(
                seg,
                v["subject"],
                tracked_frames,
                track_times,
                person_frames,
                person_times,
            ):
                changed += 1
    return changed


def _apply_subject(seg, side, tracked_frames, track_times, person_frames, person_times):
    """Re-target a segment's crop to the Gemini-chosen person; refresh its focal
    series so the pan follows the new track. Returns True if the subject changed."""
    cands = (seg.get("escalate", {}).get("facts") or {}).get("candidates") or []
    if not cands:
        return False
    if side == "left":
        chosen = min(cands, key=lambda c: c["x"])
    elif side == "right":
        chosen = max(cands, key=lambda c: c["x"])
    else:
        chosen = min(cands, key=lambda c: abs(c["x"] - 0.5))
    crop = seg["crops"][0]
    if crop.get("track_id") == chosen["track_id"]:
        return False
    crop["track_id"] = chosen["track_id"]
    crop["x_target"] = chosen["x"]
    crop["source"] = "face"
    seg["reason"] = f"gemini: follow {side} subject"
    if seg.get("trace"):
        seg["trace"]["trigger"] = seg["reason"]
        seg["trace"]["source"] = "gemini_subject"
    if tracked_frames is not None:
        from reframe_plan import _attach_focal_points

        _attach_focal_points(
            seg, tracked_frames, track_times, person_frames or [], person_times or []
        )
    return True

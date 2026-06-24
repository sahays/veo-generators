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

DECISION_INTRO = (
    "You are the decision engine for a 16:9 → 9:16 video reframer. Deterministic "
    "CV already measured the facts; you resolve only the calls it cannot make from "
    "pixels alone. For each decision point below you get its question, measured "
    "facts, and one or more thumbnail frames. Answer each by echoing its exact "
    "`key` and an `action`.\n"
    "TEXT decisions (key starts 'text:'):\n"
    "  • letterbox — there IS meaningful on-screen text/graphics to the side of the "
    "subject that must stay in frame; also give `coverage` = the fraction of width "
    "(0-1) that must remain visible to keep it.\n"
    "  • crop — the wide band is just background (scenery, architecture, texture); "
    "follow the subject. Judge by what you SEE, not band width — a busy background "
    "is not text.\n"
    "SUBJECT decisions (key starts 'subject:'): answer action=follow and `subject` = "
    "left | center | right — the one person the viewer should track (the speaker / "
    "main focus). Use the thumbnail and the listed positions.\n"
    "Return exactly one verdict per key."
)


def build_cluster_block(cluster: dict) -> str:
    """The text describing one decision point (its thumbnails follow as image parts)."""
    return (
        f"\n[key={cluster['key']}] {cluster['question']}\n"
        f"facts: {json.dumps(cluster['facts'])}\n"
        f"(thumbnail{'s' if len(cluster['thumb_secs']) != 1 else ''} below)"
    )


def extract_thumbnails(video_path: str, secs: List[float]) -> dict:
    """Decode JPEG bytes for each requested second → {round(sec, 2): bytes}.

    Best-effort (cv2): a frame that can't be read is omitted; the Gemini call
    then sends that cluster text-only. Degrades to {} if cv2 is unavailable.
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
        for t in sorted({round(float(s), 2) for s in secs}):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                out[t] = buf.tobytes()
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

"""Helper functions for reframe Pass-2 Gemini decision prompts, overlays, and letterbox harmonization."""

import json
from typing import Any, List, Optional, Tuple

from reframe_plan import _seg_has_face, rung_coverage

THUMBS_PER_CLUSTER = 3

_DECISION_INTRO_TMPL = (
    "You are the decision engine for a 16:9 → {canvas} (portrait) video reframer. "
    "Deterministic CV handles geometry; you resolve only what needs human-like "
    "judgment from the pixels. Each decision point below gives its `key`, a "
    "question, and SEVERAL thumbnail frames sampled across that shot. The frames "
    "are ANNOTATED to show what a tight portrait crop would do:\n"
    "  • the GREEN box = the region the crop keeps; the DARKENED area = what gets "
    "cut off.\n"
    "  • for subject choices, vertical lines mark each candidate person, labeled "
    "left / center / right.\n"
    "Answer each point by echoing its exact `key` and an `action`.\n"
    "TEXT decisions (key 'text:…') — a pure READABILITY check. Look at the DARKENED "
    "(cut) area across the frames and ask ONLY: can you read any letters or words "
    "there? Do NOT weigh whether that text is important, vital, essential, "
    "decorative, branding, or 'just an overlay' — importance is IRRELEVANT to this "
    "decision.\n"
    "  • letterbox — you can read ANY text/label/word/graphic in the cut area (a "
    "product call-out, feature or spec label, caption, title, logo, chart, map, "
    "UI, price, %) that would be clipped, even partially, and even while a person "
    "is the moving/centered subject. If it is READABLE and would be cut, letterbox. "
    "Give `coverage` = fraction of width (0-1) to keep it fully visible.\n"
    "  • crop — ONLY when the cut area has ZERO readable characters: it is pure "
    "background (scenery, building, landscape, plants, wall, blur, out-of-focus "
    "decor) or a bare person/limb in front of it. Never crop away text you can "
    "read.\n"
    "SUBJECT decisions (key 'subject:…'): action=follow and `subject` = left | "
    "center | right — the one person to track (whoever is speaking / the focus).\n"
    "SPEAKER decisions (key 'speaker:…') — usually ONE person is talking: "
    "action=follow and `subject` = left | center | right for the person who is "
    "SPEAKING (open / moving mouth, mid-gesture, others listening); this person "
    "will be centered. If NO one on screen is actually talking (a static poster, "
    "key art, title card, or graphic with off-screen narration), answer "
    "action=letterbox to keep it full width instead. If the point's question "
    "offers it and this is a genuine two-shot conversation where both people "
    "matter equally, action=keep_both frames both together; action=split (only "
    "when offered) stacks the two as panels.\n"
    "NO-SUBJECT decisions (key 'nosubj:…') — no person is in frame: action=letterbox "
    "if it's a full-frame graphic/slide (chart, map, UI, title) that the darkened "
    "crop would cut off, else crop for plain scenery/b-roll.\n"
    "GRAPHIC-OR-SUBJECT decisions (key 'graphic:…') — judge from the pixels, do "
    "NOT assume a person is present: action=letterbox if the frame is a full-screen "
    "logo/ident, title/brand card, text slide, chart, map, or UI whose readable "
    "content the darkened crop would cut off; action=crop only if a real person or "
    "live-action scene is the main subject.\n"
    "Return exactly one verdict per key."
)


def build_decision_intro(canvas: str = "9:16") -> str:
    """The decision-engine system prompt, keyed to the target output canvas."""
    return _DECISION_INTRO_TMPL.format(canvas=canvas)


def build_cluster_block(cluster: dict) -> str:
    """The text describing one decision point (its annotated frames follow)."""
    return (
        f"\n[key={cluster['key']}] {cluster['question']}\n"
        f"facts: {json.dumps(cluster['facts'])}\n"
        "(annotated frames for this key follow)"
    )


def _overlay_text(frame: Any, crop_keeps: List[float]) -> Any:
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


def _overlay_subjects(frame: Any, candidates: List[dict]) -> Any:
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


def _cluster_sample_secs(cluster: dict) -> List[float]:
    """Times to sample a cluster's representative frames at."""
    s, e = cluster["start"], cluster["end"]
    thumbs = cluster.get("thumb_secs") or []
    if len(thumbs) > 1:
        return thumbs[:THUMBS_PER_CLUSTER]
    if e > s:
        fracs = (0.2, 0.5, 0.8)[:THUMBS_PER_CLUSTER]
        return [s + (e - s) * f for f in fracs]
    return thumbs[:THUMBS_PER_CLUSTER] or [s]


def _render_cluster_thumbs(
    cap: Any, c: dict, active_area: Optional[dict], cv2: Any, slice_frame: Any
) -> List[bytes]:
    secs = _cluster_sample_secs(c)
    facts = c.get("facts") or {}
    imgs: List[bytes] = []
    for t in secs:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        frame = slice_frame(frame, active_area)
        if facts.get("crop_keeps"):
            frame = _overlay_text(frame, facts["crop_keeps"])
        elif facts.get("candidates"):
            frame = _overlay_subjects(frame, facts["candidates"])
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            imgs.append(buf.tobytes())
    return imgs


def _widen_neighbor(
    nb: dict,
    target: Tuple[int, int],
    reason: str,
    ladder_idx: dict,
    src_w: int,
    src_h: int,
) -> bool:
    cur = tuple(nb["inner_ar"]) if nb.get("inner_ar") else None
    if cur not in ladder_idx or ladder_idx[cur] >= ladder_idx[target]:
        return False
    nb["inner_ar"] = target
    nb["reason"] = reason
    trace = nb.get("trace")
    if trace:
        trace.update(
            {
                "chosen_ar": list(target),
                "coverage": round(rung_coverage(target, src_w, src_h), 3),
                "trigger": reason,
                "source": "gemini_text",
            }
        )
    return True


def _extend_letterbox_walk(
    segments: List[dict],
    i: int,
    step: int,
    seg: dict,
    target: Tuple[int, int],
    reason: str,
    ladder_idx: dict,
    src_w: int,
    src_h: int,
) -> int:
    changed = 0
    k = i + step
    while 0 <= k < len(segments):
        boundary_seg = segments[k] if step > 0 else segments[k + 1]
        if boundary_seg.get("starts_at_cut", True):
            break
        nb = segments[k]
        if (
            nb.get("layout") == "split"
            or _seg_has_face(nb) != _seg_has_face(seg)
            or (nb.get("trace") or {}).get("text_measured", 0.0) <= 0.0
        ):
            break
        if _widen_neighbor(nb, target, reason, ladder_idx, src_w, src_h):
            changed += 1
        k += step
    return changed


def _harmonize_sandwich(
    segments: List[dict],
    ladder: List[Tuple[int, int]],
    ladder_idx: dict,
    src_w: int,
    src_h: int,
) -> int:
    changed = 0
    for i in range(1, len(segments) - 1):
        mid, a, b = segments[i], segments[i - 1], segments[i + 1]
        a_ok = (a.get("trace") or {}).get("source") == "gemini_text" and a.get(
            "inner_ar"
        )
        b_ok = (b.get("trace") or {}).get("source") == "gemini_text" and b.get(
            "inner_ar"
        )
        mid_is_text = (mid.get("trace") or {}).get(
            "source"
        ) == "gemini_text" and mid.get("inner_ar")
        if (
            not (a_ok and b_ok)
            or mid_is_text
            or tuple(a["inner_ar"]) != tuple(b["inner_ar"])
        ):
            continue
        if mid.get("starts_at_cut", True) or b.get("starts_at_cut", True):
            continue
        if mid.get("layout") == "split" or _seg_has_face(mid) != _seg_has_face(a):
            continue
        target = tuple(a["inner_ar"])
        if target in ladder and _widen_neighbor(
            mid,
            target,
            f"{a.get('reason', 'gemini: letterbox')} (bridged dip)",
            ladder_idx,
            src_w,
            src_h,
        ):
            changed += 1
    return changed


def _pick_candidate_by_side(cands: List[dict], side: str) -> dict:
    if side == "left":
        return min(cands, key=lambda c: c["x"])
    if side == "right":
        return max(cands, key=lambda c: c["x"])
    ordered = sorted(cands, key=lambda c: c["x"])
    if len(ordered) % 2 == 1:
        return ordered[len(ordered) // 2]
    return min(ordered, key=lambda c: abs(c["x"] - 0.5))

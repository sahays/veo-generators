"""Escalation-point builders — the questions Pass 2 asks gemini.

Each builder returns a `make_point` payload for one fuzzy decision the CPU
cannot settle from geometry (text-vs-background, which subject, who is
speaking, graphic-vs-person). `reframe_plan._decide_segment` attaches these to
segments; `reframe_escalation` batches them; `reframe_decide` applies the
verdicts. Pure logic, no I/O.
"""

import statistics
from typing import List, Optional, Tuple

from reframe_escalation import make_point
from reframe_rungs import rung_coverage
from reframe_signals import _hint_x

# Subject-choice escalation (decision points #3/#4): when framing ONE of several
# comparable faces and no face is clearly speaking, the CPU can't tell who the
# subject is — escalate to gemini-3.5-flash. Only fires when the 2nd-most-visible
# face is at least this fraction as present as the most-visible (else one clearly
# dominates and we just follow it).
SUBJECT_AMBIG_RATIO = 0.6

# Text escalation (decision point #1): the morphology detector CANNOT tell a real
# side caption from a busy/white background (proven — span/contrast/bimodality all
# overlap). So when a wide band would be CLIPPED by the subject's tight crop, the
# planner doesn't guess: it emits an escalation for gemini-3.5-flash and meanwhile
# follows the subject (the fallback). SIDE_TEXT_MARGIN is how far past the crop
# window the band must reach to count as "on the side" (vs behind the subject).
SIDE_TEXT_MARGIN = 0.06


def _tight_window(x: float, src_w: int, src_h: int, rungs) -> Tuple[float, float]:
    """(left, right) of the TIGHTEST rung's crop window centered on x — what a
    full-bleed crop keeps. Escalation questions/thumbnails show this window."""
    tight = rung_coverage(rungs[0], src_w, src_h)
    return x - tight / 2, x + tight / 2


def _candidate_facts(stable: List[dict]) -> List[dict]:
    """x-sorted candidate records for speaker/subject escalation facts.

    Carries measured w so a `keep_both` verdict can size its span; `pos` labels
    are collision-disambiguated so a `subject=center` answer is unambiguous.
    """
    cands = sorted(stable, key=lambda s: s["x"])
    pos = _candidate_labels(cands)
    return [
        {
            "track_id": s["track_id"],
            "x": round(s["x"], 3),
            "w": round(s["w"], 3),
            "frac": round(s["frac"], 2),
            "pos": p,
        }
        for s, p in zip(cands, pos)
    ]


def _candidate_labels(cands: List[dict]) -> List[str]:
    """Position labels for x-sorted candidates, disambiguated on collision.

    `_side_of` buckets two close faces (e.g. x=0.45 and 0.55) both as "center",
    which makes a `subject=center` verdict ambiguous — the model's answer and
    `_apply_subject`'s pick could land on different people. When buckets collide,
    fall back to rank-by-x labels so every candidate is uniquely addressable.
    (>3 candidates can't be disambiguated by a 3-way label anyway — keep buckets.)
    """
    pos = [_side_of(c["x"]) for c in cands]
    if len(set(pos)) < len(pos):
        if len(cands) == 2:
            pos = ["left", "right"]
        elif len(cands) == 3:
            pos = ["left", "center", "right"]
    return pos


def _text_note(facts: dict, question: str, text_esc: Optional[dict]):
    """Fold a coexisting text-band conflict into a speaker/subject question.

    A segment can have BOTH a wide text band the crop would clip AND a
    speaker/subject ambiguity — but a segment carries one escalation, and the
    speaker/subject point replaces the text point. Without this note the model
    is never told text is at stake and a press-quote/caption gets cropped
    (observed at 5.9-12.9s on rf-udcpl2hd). Carries the measured band so a
    `letterbox` answer without coverage widens to the band, not full 16:9.
    Returns the augmented (facts, question).
    """
    if not text_esc or text_esc.get("kind") != "text_presence":
        return facts, question
    tf = text_esc.get("facts") or {}
    facts = {
        **facts,
        "text_coverage": tf.get("text_coverage"),
        "band": tf.get("band"),
    }
    side = tf.get("check_side", "a")
    question += (
        f" ALSO: a wide on-screen band was measured on the {side} side that a "
        "tight centered crop would cut off. If that is REAL readable text or "
        "graphics that would be lost (a caption, quote, title, lower-third), "
        "answer action=letterbox (with coverage = fraction of width to keep) "
        "instead of centering one person."
    )
    return facts, question


def _maybe_speaker_escalation(
    stable, start, end, speaker_label=None, pair=None, can_split=False, text_esc=None
):
    """Decision point #4: which visible person is the one SPEAKING (to center).

    Fires for a multi-person shot with speech where the CPU couldn't pin the
    speaker by mouth motion. The fallback follows the most-visible face. The
    `candidates` facts drive the thumbnail's per-person markers (reused from
    subject_choice), and the verdict re-centers on the chosen person.

    `speaker_label` (the window's dominant diarization speaker_id) is folded into
    the key so adjacent turns by DIFFERENT speakers stay separate through merge,
    while same-speaker subdivisions still recombine.

    `pair` / `can_split`: when the two-shot geometry would support keep-both (or
    a stacked split), offer those as verdict options too — otherwise a genuine
    wide two-person conversation could ONLY be answered with one centered person
    or a letterbox, making keep-both/split structurally unreachable for any shot
    with speech (which is exactly when dialogue happens).
    """
    if len(stable) < 2:
        return None
    labels = _candidate_facts(stable)
    fallback_tgt = max(stable, key=lambda s: s["frac"])
    sig = ",".join(f"{round(c['x'], 1)}" for c in labels)
    question = (
        "Several people are visible ("
        + "; ".join(f"{c['pos']} at x={c['x']}" for c in labels)
        + "). Who is SPEAKING right now? Watch for lip movement, gesture and "
        "engagement, and pick the one person to center (action=follow, subject="
        "left / center / right). BUT if no one on screen is actually talking — "
        "it's a static poster, key art, title, or graphic with off-screen "
        "narration — answer action=letterbox to keep it full width instead."
    )
    facts = {"candidates": labels, "n_faces": len(stable)}
    if pair:
        facts["pair"] = [p["track_id"] for p in pair]
        facts["can_keep_both"] = True
        question += (
            " If this is a genuine two-person conversation where BOTH people "
            "matter equally (a true two-shot, neither one the clear focus), "
            "answer action=keep_both to frame both together instead."
        )
        if can_split:
            facts["can_split"] = True
            question += (
                " If they are far apart and near-static, action=split stacks "
                "them as two panels so both stay large."
            )
    facts, question = _text_note(facts, question, text_esc)
    return make_point(
        kind="active_speaker",
        key=f"speaker:{speaker_label}:{sig}" if speaker_label else f"speaker:{sig}",
        question=question,
        facts=facts,
        fallback={"action": "follow", "subject": _side_of(fallback_tgt["x"])},
        start=start,
        end=end,
    )


def _competitors(stable, mouth) -> list:
    """Compact per-face record (for the decision trace / observability)."""
    out = []
    for s in stable:
        m = mouth.get(s["track_id"], []) if mouth else []
        out.append(
            {
                "track_id": s["track_id"],
                "x": round(s["x"], 3),
                "w": round(s["w"], 3),
                "conf": round(s.get("conf", 0.5), 3),
                "frac": round(s["frac"], 2),
                "mouth_var": round(statistics.pstdev(m), 3) if len(m) >= 3 else None,
            }
        )
    return out


def _maybe_text_escalation(text_band, subj_x, n_faces, src_w, src_h, rungs, start, end):
    """Decision point #1: a wide text band that the subject's tight crop would clip.

    Returns a `text_presence` escalation point (for gemini-3.5-flash) or None.
    None means no conflict — no persistent wide band, or it sits *within* the crop
    window (behind the subject). A band that pokes past the window by >
    SIDE_TEXT_MARGIN on a side is the ambiguous case the morphology detector can't
    resolve (real caption vs busy background) → escalate; the fallback follows the
    subject (crop) until the verdict comes back. This is now the ONLY path to a
    text letterbox — there is no CPU self-trigger and no Gemini coverage floor.
    """
    cov, (x0, x1) = text_band
    if cov <= 0.0:
        return None  # no text present in the window
    # Significance is a per-side REACH property, not a total-width one: a caption
    # narrower than any fixed width floor is still clip-worthy when it sits past the
    # crop window. The poke-out test below IS the significance gate — a band fully
    # behind the subject is kept by the crop and never escalates.
    wl, wr = _tight_window(subj_x, src_w, src_h, rungs)
    left_out = (wl - x0) > SIDE_TEXT_MARGIN
    right_out = (x1 - wr) > SIDE_TEXT_MARGIN
    if not (left_out or right_out):
        return None  # band sits behind the subject → a tight crop keeps it
    side = "both" if (left_out and right_out) else ("left" if left_out else "right")
    where = "either side" if side == "both" else f"the {side}"
    # NEUTRAL, image-first question. Do NOT assert text exists (the CPU band is a
    # known false-positive over busy backgrounds) — make Gemini judge from pixels.
    return make_point(
        kind="text_presence",
        key=f"text:{side}:{round(x0, 1)}-{round(x1, 1)}@{round(subj_x, 1)}",
        question=(
            f"A tight vertical crop will center on the subject (~x={subj_x:.2f}) and "
            f"cut off {where}. Look at the frame: on that side, is there READABLE "
            "on-screen text or a graphic (caption, title, lower-third, chart/table, "
            "UI, logo) that would be lost? A person in front of scenery, a building, "
            "plants, or a textured wall is NOT a graphic — answer crop unless real "
            "readable text/graphics would be cut off."
        ),
        facts={
            "subject_x": round(subj_x, 3),
            "crop_keeps": [round(wl, 3), round(wr, 3)],
            "check_side": side,
            "n_faces": n_faces,
            # The measured band, so a `letterbox` verdict that omits `coverage`
            # widens to the band's extent instead of jumping to full 16:9
            # (apply_verdicts falls back to text_coverage).
            "text_coverage": round(cov, 3),
            "band": [round(x0, 3), round(x1, 3)],
        },
        fallback={"action": "crop", "reason": "follow subject pending Gemini verdict"},
        start=start,
        end=end,
    )


def _side_of(x: float) -> str:
    """Coarse horizontal position label for a subject center."""
    return "left" if x < 0.4 else ("right" if x > 0.6 else "center")


def _maybe_subject_escalation(stable, fallback_tgt, start, end, text_esc=None):
    """Decision points #3/#4: which of several comparable faces is the subject.

    Returns a `subject_choice` escalation (for gemini-3.5-flash) or None. Fires
    only when 2+ faces are comparably present (the 2nd ≥ SUBJECT_AMBIG_RATIO of the
    1st) — otherwise one clearly dominates and we just follow it. Caller has already
    confirmed no face is clearly *speaking* (that resolves it deterministically).
    The fallback is the deterministic pick (`fallback_tgt`). `text_esc` folds a
    coexisting text-band conflict into the question (see `_text_note`).
    """
    if len(stable) < 2:
        return None
    by_vis = sorted(stable, key=lambda s: -s["frac"])
    if (
        by_vis[0]["frac"] <= 0
        or by_vis[1]["frac"] / by_vis[0]["frac"] < SUBJECT_AMBIG_RATIO
    ):
        return None
    labels = _candidate_facts(stable)
    facts = {"candidates": labels, "n_faces": len(stable)}
    question = (
        "Multiple people are visible ("
        + "; ".join(f"{c['pos']} at x={c['x']}" for c in labels)
        + "). Which one is the main subject to follow?"
    )
    facts, question = _text_note(facts, question, text_esc)
    return make_point(
        kind="subject_choice",
        key="subject:" + ",".join(f"{round(c['x'], 1)}" for c in labels),
        question=question,
        facts=facts,
        fallback={"action": "follow", "subject": _side_of(fallback_tgt["x"])},
        start=start,
        end=end,
    )


def _no_subject_escalation(scene, src_w, src_h, rungs, start, end):
    """Decision point #7: a shot with no detected subject (no face/person/text).

    Could be a full-frame graphic (chart, map, UI, slide → keep full width) or
    plain scenery/b-roll (center crop is fine) — the CPU can't tell, so escalate
    to gemini-3.5-flash. `crop_keeps` lets the thumbnail show what a center crop
    would cut. Fallback: center crop.
    """
    x = _hint_x(scene)
    wl, wr = _tight_window(x, src_w, src_h, rungs)
    return make_point(
        kind="no_subject",
        key=f"nosubj:{round(start, 1)}",
        question=(
            "No face or person is detected in this shot. Is it a full-frame "
            "GRAPHIC — a chart, map, table, UI, diagram, title card, or text slide "
            "— that should keep its full width (letterbox)? Or is it scenery / "
            "b-roll / background with no specific subject, where a center crop is "
            "fine (crop)? Letterbox only if content would be cut off."
        ),
        facts={"subject": "none", "crop_keeps": [round(wl, 3), round(wr, 3)]},
        fallback={"action": "crop", "reason": "center crop pending Gemini verdict"},
        start=start,
        end=end,
    )


def _maybe_graphic_escalation(tgt, src_w, src_h, rungs, start, end):
    """Decision point #7b: a SOLE, low-confidence face that might be a graphic.

    The FaceDetector runs at a low confidence floor so it doesn't miss real faces;
    the cost is that it also fires on logos / title cards / channel bugs. When the
    only subject is a single face below FACE_CONF_MIN, the CPU can't tell a real
    person (crop) from a full-frame graphic (keep full width / letterbox), so it
    escalates to gemini-3.5-flash. Fallback: follow the face crop (current
    behaviour — no regression if Gemini is unavailable). `crop_keeps` lets the
    thumbnail show what the tight crop would cut.
    """
    x = tgt["x"]
    wl, wr = _tight_window(x, src_w, src_h, rungs)
    return make_point(
        kind="weak_subject",
        key=f"graphic:{round(start, 1)}",
        # NEUTRAL, image-first. Do NOT assert a face/person exists — the detector
        # fires on logos too, and asserting "a face is here" primes the model to
        # hallucinate a person on a title card (observed on rf-udcpl2hd). Let it
        # judge from pixels (mirrors the text_presence prompt's stance).
        question=(
            "Look at the frame. Is it a full-screen GRAPHIC — a channel logo or "
            "ident, a title/brand card, a text slide, chart, map, or UI screen — "
            "whose readable logo/text spans the width so a tight vertical crop "
            "(the green box) would cut part of it off? If so, keep full width "
            "(letterbox). If instead a real PERSON or live-action scene is the "
            "main subject, follow it (crop). Judge only from what you see; "
            "letterbox only if real readable text/graphics would be cut off."
        ),
        facts={
            "subject_x": round(x, 3),
            "crop_keeps": [round(wl, 3), round(wr, 3)],
            "face_conf": round(tgt.get("conf", 0.5), 3),
        },
        fallback={"action": "crop", "reason": "follow face pending Gemini verdict"},
        start=start,
        end=end,
    )

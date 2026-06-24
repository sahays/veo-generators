"""Reframe v2 decision layer — turn detections into a per-segment crop plan.

Pure logic: no I/O, no cv2/ffmpeg. Segments come from scene cuts (subdivided so a
long take is re-decided periodically); per segment it chooses an inner aspect ratio
(how much to crop vs. letterbox) and which subject(s) to follow, from MediaPipe face
/ person tracks, a CPU-measured wide-text band, and an optional diarization dialogue
signal. Borderline judgments are emitted as escalation points for Pass 2
(gemini-3.5-flash) rather than guessed — see `reframe_escalation` / `reframe_decide`.
Gemini scene labels are accepted if supplied (diagnostic mode) but are no longer the
primary driver: the retired dense Pro pass used to force a coverage floor that
over-letterboxed plain shots.

Output is a list of SegmentPlan dicts consumed by the renderer:
    {start, end, layout, inner_ar, crops:[{track_id, x_target, keypoints}], reason}
"""

import bisect
import math
import statistics
from typing import List, Optional, Tuple

# Inner-AR rungs, tightest crop → loosest (most letterbox). Chosen by coverage.
# 9:16 is the historical *adaptive* ladder: each scene picks a rung, letterboxing
# wide content. 3:4 is a *fixed* full-bleed crop — a single-rung ladder so every
# scene crops to fill the 3:4 frame (subject-following pan), never letterboxes.
RUNGS: List[Tuple[int, int]] = [(9, 16), (4, 5), (1, 1), (16, 9)]
RUNGS_BY_CANVAS: dict = {
    "9:16": RUNGS,
    "3:4": [(3, 4)],
}

MIN_DWELL = 2.0  # merge segments shorter than this (seconds)
MAX_SEG_LEN = 5.0  # re-decide framing at least this often, even with no cut
MERGE_X_TOL = 0.08  # only merge same-framing neighbours if the crop center agrees
COVERAGE_MARGIN = 0.04  # safety margin added to measured detection width
RUNG_TOLERANCE = 0.05  # accept a rung that covers within this of the requirement
KEEP_BOTH_SEPARATION = 0.30  # min face-center separation for keep-both
STABLE_FRAC = 0.30  # a track must appear in ≥ this fraction of segment frames
# A single subject can never need full width — cap its coverage demand so a huge
# (foreground / mis-measured) detection doesn't force 16:9 letterbox.
FACE_W_CAP = 0.45  # → at most 1:1 from a single face
PERSON_W_CAP = 0.60  # bodies are wider than faces, but still bounded

# Active-speaker detection (Phase 2): in a multi-person shot, frame the talking
# face (mouth moving) as a single crop instead of letterboxing both. Speaking is
# measured as the variance of each track's mouth-aspect-ratio over the segment.
SPEAKER_MIN_SAMPLES = 3  # need this many mouth samples to judge a track
SPEAKER_MIN_ACTIVITY = 0.03  # MAR stdev below this = not talking
SPEAKER_DOMINANCE = 1.6  # the speaker's activity must beat the 2nd by this factor
# Subject-choice escalation (decision points #3/#4): when framing ONE of several
# comparable faces and no face is clearly speaking, the CPU can't tell who the
# subject is — escalate to gemini-3.5-flash. Only fires when the 2nd-most-visible
# face is at least this fraction as present as the most-visible (else one clearly
# dominates and we just follow it).
SUBJECT_AMBIG_RATIO = 0.6

# Wide-text detection (Phase 2): the CPU measures a persistent wide text band so
# the planner can ask Gemini the right question when it would be clipped (decision
# point #1). The CPU never self-letterboxes from it — see _maybe_text_escalation.
TEXT_WIDE_MIN = 0.50  # a sampled frame counts as wide-text at/above this coverage
TEXT_PERSIST_FRAC = 0.50  # text must show in ≥ this fraction of a segment's frames
# Text escalation (decision point #1): the morphology detector CANNOT tell a real
# side caption from a busy/white background (proven — span/contrast/bimodality all
# overlap). So when a wide band would be CLIPPED by the subject's tight crop, the
# planner doesn't guess: it emits an escalation for gemini-3.5-flash and meanwhile
# follows the subject (the fallback). SIDE_TEXT_MARGIN is how far past the crop
# window the band must reach to count as "on the side" (vs behind the subject).
SIDE_TEXT_MARGIN = 0.06

# Vertical-split layout (Phase 3): when two speakers sit too far apart for even a
# 1:1 rung to hold both at a decent size, stack them as two full-canvas panels so
# both read large. Stacking destroys eyeline/spatial continuity, so it is gated
# hard — only a *static, persistent, two-person dialogue* qualifies; everything
# else keeps the single/keep-both crop. left subject → top panel, right → bottom.
SPLIT_MIN_SEPARATION = 0.45  # face-center gap above which 1:1 shrinks both too far
SPLIT_MIN_FRAC = 0.80  # both tracks must be near-continuously present
SPLIT_MIN_DWELL = 3.0  # only for shots that hold long enough to read as intentional
SPLIT_MAX_MOTION = 0.06  # near-static: each track's x-span must stay below this

# Diarization-derived dialogue signal. The dense Gemini scene pass (which used to
# label "dialogue" / "side_by_side") was retired, so keep-both and split would
# never fire in production (scene is always {}). Chirp diarization already runs;
# a window where two distinct speakers each hold the floor for ≥ this many seconds
# IS the two-person-dialogue signal those layouts need. Supplied to reconcile as
# `speaker_segments` and injected as scene_type="dialogue" when no scene label set.
DIALOGUE_MIN_SPEAK = 0.5  # seconds a speaker must talk in a window to count

# Pan smoothing per Gemini scene_type → (max_velocity frac/s, deadzone frac).
# Replaces the old global content_type setting: framing adapts per scene, so an
# action beat and a dialogue beat in the same video pan differently. Deadzones
# are small: a large deadzone freezes the crop at the first (often off-center)
# keypoint and never re-centers — keep just enough to suppress detection jitter.
SCENE_TYPE_PARAMS: dict[str, Tuple[float, float]] = {
    "dialogue": (0.10, 0.02),  # hold steady on speakers
    "close-up": (0.08, 0.02),  # very stable
    "action": (0.50, 0.02),  # track fast motion
    "establishing": (0.10, 0.02),
    "wide": (0.10, 0.02),
    "general": (0.15, 0.02),
}
DEFAULT_SCENE_PARAMS: Tuple[float, float] = (0.15, 0.02)
# With the dense Gemini scene pass retired, scene_type is derived from MEASURED
# motion: a subject whose x-center ranges more than this across a segment is
# "action" (pan fast); otherwise "general". More accurate than a coarse label.
ACTION_SPREAD = 0.25
# If the subject's x barely moves across a segment, center on its median
# position (robust to boundary jitter) instead of a velocity-limited path that
# can lock off-center.
STATIC_SPREAD = 0.10


# ---------------------------------------------------------------------------
# Rung selection
# ---------------------------------------------------------------------------


def rung_coverage(rung: Tuple[int, int], src_w: int, src_h: int) -> float:
    """Fraction of source width a rung's crop keeps (clamped to 1.0)."""
    aw, ah = rung
    return min(1.0, (src_h * aw / ah) / src_w)


def pick_rung(
    required: float,
    src_w: int,
    src_h: int,
    prev: Optional[Tuple[int, int]] = None,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> Tuple[int, int]:
    """Lowest rung whose coverage ≥ required.

    Hysteresis: if the previous rung still covers the content and is at most one
    rung looser than ideal, keep it (avoids single-step flip-flopping). A larger
    gap still tightens so we never stay needlessly letterboxed.

    A small RUNG_TOLERANCE lets a tighter rung win when it *almost* covers the
    requirement — trading a sliver of edge crop for much less letterboxing (e.g.
    a two-shot needing 0.60 takes 1:1 at 0.5625 rather than full 16:9).

    `rungs` is the canvas's ladder (defaults to the 9:16 RUNGS).
    """
    rungs = rungs or RUNGS
    ideal = next(
        (
            r
            for r in rungs
            if rung_coverage(r, src_w, src_h) + RUNG_TOLERANCE >= required
        ),
        rungs[-1],
    )
    if (
        prev is not None
        and prev in rungs
        and rung_coverage(prev, src_w, src_h) + RUNG_TOLERANCE >= required
    ):
        if 0 <= rungs.index(prev) - rungs.index(ideal) <= 1:
            return prev
    return ideal


# ---------------------------------------------------------------------------
# Track aggregation within a time window
# ---------------------------------------------------------------------------


def _global_label_map(tracked_frames: List[dict]) -> dict:
    """label (A,B,…) → track_id, ranked by global visibility (matches Gemini context)."""
    counts: dict = {}
    for frame in tracked_frames:
        for t in frame.get("tracks", []):
            counts[t["track_id"]] = counts.get(t["track_id"], 0) + 1
    ranked = sorted(counts, key=lambda tid: -counts[tid])
    return {
        (chr(ord("A") + i) if i < 26 else str(tid)): tid for i, tid in enumerate(ranked)
    }


def _window(frames, times, start, end):
    """Frames whose time_sec is in [start, end], via bisect on the prebuilt
    `times` index.

    `times` is a once-computed sorted list of each frame's time_sec, aligned with
    `frames`. Slicing through it makes every per-segment aggregation O(log F + w)
    over its window instead of an O(F) rescan of the whole series per segment.
    """
    lo = bisect.bisect_left(times, start)
    hi = bisect.bisect_right(times, end)
    return frames[lo:hi]


def _stable_tracks(win):
    """Mean x/w and visibility fraction per track over the windowed frames."""
    if not win:
        return []
    agg: dict = {}
    for f in win:
        for t in f.get("tracks", []):
            a = agg.setdefault(t["track_id"], {"xs": [], "ws": []})
            a["xs"].append(t["x"])
            a["ws"].append(t.get("w", 0.0))
    n = len(win)
    stats = [
        {
            "track_id": tid,
            "x": sum(a["xs"]) / len(a["xs"]),
            "w": sum(a["ws"]) / len(a["ws"]),
            "frac": len(a["xs"]) / n,
        }
        for tid, a in agg.items()
    ]
    return [s for s in stats if s["frac"] >= STABLE_FRAC]


# ---------------------------------------------------------------------------
# Entity matching (Gemini hint → a concrete track)
# ---------------------------------------------------------------------------


def _hint_x(scene: dict) -> float:
    h = (scene.get("active_subject") or "").lower()
    if "left" in h:
        return 0.3
    if "right" in h:
        return 0.7
    return 0.5


def _match_track(stable: List[dict], scene: dict, label_map: dict) -> dict:
    """Resolve the active subject to one stable track (geometric, not id-order)."""
    import re

    h = (scene.get("active_subject") or "").lower()
    m = re.search(r"track\s+([a-z])", h)
    if m:
        tid = label_map.get(m.group(1).upper())
        match = next((s for s in stable if s["track_id"] == tid), None)
        if match:
            return match
    if "left" in h:
        return min(stable, key=lambda s: s["x"])
    if "right" in h:
        return max(stable, key=lambda s: s["x"])
    if "center" in h:
        return min(stable, key=lambda s: abs(s["x"] - 0.5))
    return max(stable, key=lambda s: s["frac"])  # most prominent


def pick_active_speaker(track_mouth: dict) -> Optional[int]:
    """Track id of the clearly-talking face, or None if ambiguous/silent.

    `track_mouth` maps track_id → list of mouth-aspect-ratio samples over the
    window. Talking makes the ratio oscillate (high variance); a listener's
    mouth is ~steady. Returns a speaker only when one track's activity clearly
    dominates — otherwise None so the caller keeps both in frame.
    """
    acts = {
        tid: statistics.pstdev(v)
        for tid, v in track_mouth.items()
        if len(v) >= SPEAKER_MIN_SAMPLES
    }
    if not acts:
        return None
    ranked = sorted(acts.items(), key=lambda kv: -kv[1])
    top_tid, top = ranked[0]
    if top < SPEAKER_MIN_ACTIVITY:
        return None  # nobody clearly talking
    if len(ranked) > 1 and ranked[1][1] * SPEAKER_DOMINANCE > top:
        return None  # two mouths moving → ambiguous, keep both
    return top_tid


def _segment_track_mouth(win, track_ids) -> dict:
    """Per-track mouth-aspect-ratio samples over the windowed frames."""
    ids = set(track_ids)
    out: dict = {tid: [] for tid in ids}
    for f in win:
        for tr in f.get("tracks", []):
            m = tr.get("mouth")
            if tr["track_id"] in ids and m is not None:
                out[tr["track_id"]].append(m)
    return out


def _keep_both_pair(stable: List[dict], scene: dict):
    """Return the two far-apart tracks to keep, or None for a single-subject crop."""
    if len(stable) < 2:
        return None
    layout = (scene.get("layout") or "").lower()
    by_vis = sorted(stable, key=lambda s: -s["frac"])[:2]
    sep = abs(by_vis[0]["x"] - by_vis[1]["x"])
    wants_both = layout == "side_by_side" or scene.get("scene_type") == "dialogue"
    if sep >= KEEP_BOTH_SEPARATION and (wants_both or sep >= 0.45):
        return by_vis
    return None


def _track_x_spread(win, track_id) -> float:
    """Range of a track's x center across the windowed frames (0 if absent)."""
    xs = [p["x"] for p in _track_series(win, track_id)]
    return (max(xs) - min(xs)) if xs else 0.0


def _split_crops(pair, win, start, end, scene):
    """Two stacked panels for a static, far-apart two-person dialogue, or None.

    Gated hard (stacking breaks eyeline continuity): the two tracks must be widely
    separated, both near-continuously present, the shot must hold long enough to
    read, both panels must be near-static, and Gemini must call it a dialogue /
    side-by-side. Assignment is geometric and stable — left subject → top panel,
    right → bottom — so panels never swap mid-scene.
    """
    a, b = pair
    if abs(a["x"] - b["x"]) < SPLIT_MIN_SEPARATION:
        return None
    if min(a["frac"], b["frac"]) < SPLIT_MIN_FRAC:
        return None
    if (end - start) < SPLIT_MIN_DWELL:
        return None
    layout = (scene.get("layout") or "").lower()
    if scene.get("scene_type") != "dialogue" and layout != "side_by_side":
        return None
    left, right = sorted(pair, key=lambda s: s["x"])  # left → top, right → bottom
    if (
        _track_x_spread(win, left["track_id"]) > SPLIT_MAX_MOTION
        or _track_x_spread(win, right["track_id"]) > SPLIT_MAX_MOTION
    ):
        return None
    return [
        {"track_id": left["track_id"], "x_target": left["x"], "source": "split_top"},
        {
            "track_id": right["track_id"],
            "x_target": right["x"],
            "source": "split_bottom",
        },
    ]


# ---------------------------------------------------------------------------
# Wide-text coverage (Gemini flags, CPU measures the exact extent)
# ---------------------------------------------------------------------------


def _segment_text_band(win) -> Tuple[float, Tuple[float, float]]:
    """Median wide-text coverage AND its horizontal span over the window.

    `win` is the `text_detect.scan_video_text` frames in this segment (each with
    `coverage` and `span`). Requires wide text in ≥ TEXT_PERSIST_FRAC of them
    (rejects a one-frame flash / a swish-pan title), then returns the median
    width of those that *did* carry it, plus the median (x0, x1) of that band.

    The span is what lets the planner ask the right question: a band that sits
    *behind* the subject is harmless, but one that extends past the crop window
    on a side would be clipped — the ambiguous "is that meaningful side
    text/graphics?" case that escalates to Gemini (see _maybe_text_escalation).
    """
    if not win:
        return 0.0, (0.0, 0.0)
    wide = [f for f in win if f["coverage"] >= TEXT_WIDE_MIN]
    if len(wide) / len(win) < TEXT_PERSIST_FRAC:
        return 0.0, (0.0, 0.0)
    cov = statistics.median([f["coverage"] for f in wide])
    x0 = statistics.median([f.get("span", (0.0, 0.0))[0] for f in wide])
    x1 = statistics.median([f.get("span", (0.0, 0.0))[1] for f in wide])
    return cov, (x0, x1)


# ---------------------------------------------------------------------------
# Per-frame focal series (for intra-segment panning)
# ---------------------------------------------------------------------------


def _track_series(win, track_id):
    """The chosen face track's (time, x, y) samples over the windowed frames."""
    out = []
    for f in win:
        for tr in f.get("tracks", []):
            if tr["track_id"] == track_id:
                out.append(
                    {"time_sec": f["time_sec"], "x": tr["x"], "y": tr.get("y", 0.5)}
                )
                break
    return out


def _segment_persons(win):
    """Per-frame largest person over the windowed frames → {time_sec, x, y, w}."""
    out = []
    for f in win:
        ps = f.get("persons", [])
        if not ps:
            continue
        big = max(ps, key=lambda p: p.get("w", 0.0) * p.get("h", 0.0))
        out.append(
            {
                "time_sec": f["time_sec"],
                "x": big["x"],
                "y": big.get("y", 0.5),
                "w": big.get("w", 0.0),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Per-segment decision (always one crop in the MVP; split is Phase 3)
# ---------------------------------------------------------------------------


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
    if cov < TEXT_WIDE_MIN:
        return None
    tight = rung_coverage(rungs[0], src_w, src_h)  # rungs[0] = tightest (full-bleed)
    wl, wr = subj_x - tight / 2, subj_x + tight / 2
    left_out = (wl - x0) > SIDE_TEXT_MARGIN
    right_out = (x1 - wr) > SIDE_TEXT_MARGIN
    if not (left_out or right_out):
        return None  # band sits behind the subject → a tight crop keeps it
    from reframe_escalation import make_point

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
        },
        fallback={"action": "crop", "reason": "follow subject pending Gemini verdict"},
        start=start,
        end=end,
    )


def _side_of(x: float) -> str:
    """Coarse horizontal position label for a subject center."""
    return "left" if x < 0.4 else ("right" if x > 0.6 else "center")


def _maybe_subject_escalation(stable, fallback_tgt, start, end):
    """Decision points #3/#4: which of several comparable faces is the subject.

    Returns a `subject_choice` escalation (for gemini-3.5-flash) or None. Fires
    only when 2+ faces are comparably present (the 2nd ≥ SUBJECT_AMBIG_RATIO of the
    1st) — otherwise one clearly dominates and we just follow it. Caller has already
    confirmed no face is clearly *speaking* (that resolves it deterministically).
    The fallback is the deterministic pick (`fallback_tgt`).
    """
    if len(stable) < 2:
        return None
    by_vis = sorted(stable, key=lambda s: -s["frac"])
    if (
        by_vis[0]["frac"] <= 0
        or by_vis[1]["frac"] / by_vis[0]["frac"] < SUBJECT_AMBIG_RATIO
    ):
        return None
    from reframe_escalation import make_point

    cands = sorted(stable, key=lambda s: s["x"])
    labels = [
        {
            "track_id": s["track_id"],
            "x": round(s["x"], 3),
            "frac": round(s["frac"], 2),
            "pos": _side_of(s["x"]),
        }
        for s in cands
    ]
    return make_point(
        kind="subject_choice",
        key="subject:" + ",".join(f"{round(s['x'], 1)}" for s in cands),
        question=(
            "Multiple people are visible ("
            + "; ".join(f"{c['pos']} at x={c['x']}" for c in labels)
            + "). Which one is the main subject to follow?"
        ),
        facts={"candidates": labels, "n_faces": len(stable)},
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
    from reframe_escalation import make_point

    x = _hint_x(scene)
    tight = rung_coverage(rungs[0], src_w, src_h)
    wl, wr = x - tight / 2, x + tight / 2
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


def _decide_segment(
    scene, tf_win, pf_win, tx_win, start, end, label_map, src_w, src_h, rungs
):
    """Decide layout, focal target and required coverage for one segment.

    `tf_win`/`pf_win`/`tx_win` are the tracked-face / person / text frames already
    sliced to this segment's window (via `_window`). Falls back to person/body
    detection when no stable face is present (e.g. a subject walking away), then to
    the Gemini spatial hint. Returns the decision plus the raw inputs that drove it.

    `src_w`/`src_h`/`rungs` size the subject's tight-crop window for the text
    escalation predicate (#1).
    """
    stable = _stable_tracks(tf_win)
    # Pass 1 letterboxes ONLY from CPU subject geometry (two-shot span, wide body).
    # The retired dense Gemini scene pass used to force a rung from its coverage /
    # requires_full_width fields and over-letterboxed plain shots (the original bug);
    # that floor is gone. A persistent wide TEXT band the crop would clip is escalated
    # to gemini-3.5-flash (decision point #1) — Pass 2 decides text, never Pass 1.
    text_meas, text_span = _segment_text_band(tx_win)

    # Subject we'd crop to (face → body → spatial hint); escalate only when a wide
    # band pokes past that subject's tight crop window.
    if stable:
        subj_x = max(stable, key=lambda s: (s["frac"], -abs(s["x"] - 0.5)))["x"]
    else:
        _persons = _segment_persons(pf_win)
        if _persons and len(_persons) / max(1, len(pf_win)) >= STABLE_FRAC:
            subj_x = sum(p["x"] for p in _persons) / len(_persons)
        else:
            subj_x = _hint_x(scene)
    escalate = _maybe_text_escalation(
        (text_meas, text_span), subj_x, len(stable), src_w, src_h, rungs, start, end
    )

    def out(layout, crop, c, c_meas, faces=None, n_persons=0):
        return {
            "layout": layout,
            "crops": [crop],
            "C": min(1.0, c),
            "text_meas": round(text_meas, 3),
            "c_meas": round(c_meas, 3),
            "source": crop["source"],
            "n_faces": len(stable),
            "n_persons": n_persons,
            "faces": faces or [],
            "escalate": escalate,
        }

    # Margin pads the DETECTION-measured width (for tracker slop), not Gemini's
    # stated coverage (which is already a minimum) — avoids double-padding.
    if stable:
        mouth = _segment_track_mouth(tf_win, [s["track_id"] for s in stable])
        faces = _competitors(stable, mouth)
        pair = _keep_both_pair(stable, scene)
        if pair:
            speaker = pick_active_speaker(mouth)
            tgt = next((s for s in stable if s["track_id"] == speaker), None)
            if tgt:  # ASD: one of the two is clearly talking → frame them large
                cm = min(tgt["w"], FACE_W_CAP)
                crop = {"track_id": speaker, "x_target": tgt["x"], "source": "speaker"}
                return out("single", crop, cm + COVERAGE_MARGIN, cm, faces)

            # Neither clearly dominates: if they're too far apart for 1:1 to hold
            # both large AND the shot is a static dialogue, stack them as panels
            # instead of letterboxing both tiny.
            split = _split_crops(pair, tf_win, start, end, scene)
            if split:
                a, b = pair
                sep = abs(a["x"] - b["x"])
                return {
                    "layout": "split",
                    "crops": split,
                    "C": 1.0,  # panels fill the canvas; no rung / letterbox
                    "text_meas": round(text_meas, 3),
                    "c_meas": round(sep, 3),
                    "source": "split",
                    "n_faces": len(stable),
                    "n_persons": 0,
                    "faces": faces,
                }

            a, b = pair
            left = min(a["x"] - a["w"] / 2, b["x"] - b["w"] / 2)
            right = max(a["x"] + a["w"] / 2, b["x"] + b["w"] / 2)
            span = max(0.0, right - left)
            crop = {
                "track_id": None,
                "x_target": (a["x"] + b["x"]) / 2,
                "source": "center",
            }
            return out("keep_both", crop, span + COVERAGE_MARGIN, span, faces)

        # Single-subject pick. A clearly-speaking face resolves it deterministically
        # (#4); otherwise, among comparable faces, escalate "which subject?" (#3) and
        # follow the deterministic pick as the fallback.
        fallback_tgt = _match_track(stable, scene, label_map)
        source = "face"
        if len(stable) >= 2:
            speaker = pick_active_speaker(mouth)
            if speaker is not None:
                tgt = next(s for s in stable if s["track_id"] == speaker)
                source = "speaker"
            else:
                tgt = fallback_tgt
                escalate = (
                    _maybe_subject_escalation(stable, fallback_tgt, start, end)
                    or escalate
                )
        else:
            tgt = fallback_tgt
        cm = min(tgt["w"], FACE_W_CAP)
        crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": source}
        return out("single", crop, cm + COVERAGE_MARGIN, cm, faces)

    # No stable face → try person/body detection.
    persons = _segment_persons(pf_win)
    if persons and len(persons) / max(1, len(pf_win)) >= STABLE_FRAC:
        mean_x = sum(p["x"] for p in persons) / len(persons)
        mean_w = min(sum(p["w"] for p in persons) / len(persons), PERSON_W_CAP)
        crop = {"track_id": None, "x_target": mean_x, "source": "person"}
        return out(
            "single", crop, mean_w + COVERAGE_MARGIN, mean_w, n_persons=len(persons)
        )

    # Nothing detected (#7): no face, no person, no text band to follow. The CPU
    # can't tell a full-frame graphic (chart/map/UI/slide — keep full width) from
    # plain scenery (center crop is fine) — escalate. Fallback: center crop.
    if escalate is None:
        escalate = _no_subject_escalation(scene, src_w, src_h, rungs, start, end)
    crop = {"track_id": None, "x_target": _hint_x(scene), "source": "center"}
    return out("single", crop, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Segmentation + merging
# ---------------------------------------------------------------------------


def _boundaries(cuts: List[float], duration: float) -> List[Tuple[float, float]]:
    """Segment boundaries from cuts, subdivided so no segment exceeds MAX_SEG_LEN.

    Subdivision makes framing robust to missed cuts: a long take (or a stretch
    where cut detection failed) is re-decided every ~MAX_SEG_LEN seconds instead
    of being one stale crop. Identical neighbours are recombined later by merge.
    """
    pts = sorted({0.0, duration, *[c for c in cuts if 0.0 < c < duration]})
    out: List[Tuple[float, float]] = []
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        n = max(1, math.ceil((b - a) / MAX_SEG_LEN))
        step = (b - a) / n
        for k in range(n):
            out.append((a + k * step, b if k == n - 1 else a + (k + 1) * step))
    return out


def _dialogue_in_window(speaker_segments: List[dict], start: float, end: float) -> bool:
    """True if ≥2 distinct speakers each hold the floor within [start, end].

    Replaces the retired Gemini "dialogue" scene label with the diarization signal
    that already runs: a window where two speaker_ids each speak ≥ DIALOGUE_MIN_SPEAK
    seconds is a genuine two-person dialogue — the semantic keep-both / split need.
    Geometry gates (separation, static, dwell) still decide the layout downstream;
    this only unlocks the *intent*. `speaker_segments` are dicts with speaker_id /
    start_sec / end_sec (Chirp diarization output).
    """
    if not speaker_segments:
        return False
    talk: dict = {}
    for sp in speaker_segments:
        lo = max(start, sp.get("start_sec", 0.0))
        hi = min(end, sp.get("end_sec", 0.0))
        if hi > lo:
            sid = sp.get("speaker_id")
            talk[sid] = talk.get(sid, 0.0) + (hi - lo)
    return sum(1 for d in talk.values() if d >= DIALOGUE_MIN_SPEAK) >= 2


def _scene_for(
    scenes: List[dict], starts: List[float], start: float, end: float
) -> dict:
    """The Gemini scene covering this segment's midpoint (empty dict if none)."""
    if not scenes:
        return {}
    mid = (start + end) / 2
    i = bisect.bisect_right(starts, mid) - 1
    return scenes[max(0, i)] if i >= 0 else scenes[0]


def _merge_short(
    segments: List[dict],
    min_dwell: float,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> List[dict]:
    """Collapse identical neighbors and fold sub-dwell segments into the previous one."""
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

    def _hasface(s):
        return (s.get("trace") or {}).get("n_faces", 0) > 0

    out = [dict(segments[0])]
    for seg in segments[1:]:
        prev = out[-1]
        too_short = (seg["end"] - seg["start"]) < min_dwell
        # Same framing AND the crop is on the same spot — otherwise keep separate
        # so each subdivided cell re-frames its own subject (don't smear a pan
        # across two different subjects). ALSO never merge across a content change:
        # a different escalation decision (a caption appears) or a face↔no-face
        # transition (speaker → b-roll graphic) — else one Gemini verdict wrongly
        # governs heterogeneous shots (e.g. cropping a full-screen graphic).
        same = (
            seg["inner_ar"] == prev["inner_ar"]
            and seg["layout"] == prev["layout"]
            and abs(_cx(seg) - _cx(prev)) <= MERGE_X_TOL
            and _esc_sig(seg) == _esc_sig(prev)
            and _hasface(seg) == _hasface(prev)
        )
        if same or too_short:
            # Extend prev; keep the looser rung so we never crop out the short bit.
            # The looser-rung swap only applies between two rung-based segments —
            # a split (inner_ar=None) has no rung index, so it never swaps in/out
            # here (its strict dwell gate already keeps it from being this short).
            prev["end"] = seg["end"]
            # Carry a merged-in segment's escalation if the survivor had none, so
            # an ambiguity in the folded slice still reaches Gemini.
            if seg.get("escalate") and not prev.get("escalate"):
                prev["escalate"] = seg["escalate"]
            both_runged = isinstance(seg["inner_ar"], tuple) and isinstance(
                prev["inner_ar"], tuple
            )
            if both_runged and rungs.index(seg["inner_ar"]) > rungs.index(
                prev["inner_ar"]
            ):
                prev["inner_ar"] = seg["inner_ar"]
                prev["layout"] = seg["layout"]
                prev["crops"] = seg["crops"]
                prev["reason"] = seg["reason"]
                prev["trace"] = seg.get("trace")
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
        trig += f"; widened from {ideal[0]}:{ideal[1]} (hysteresis)"
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


def _motion_scene_type(d: dict, tf_win, pf_win) -> str:
    """Pan profile from MEASURED subject motion (replaces the Gemini scene_type).

    The chosen subject's x-center range across the segment: a wide range means the
    subject moves a lot → "action" (pan fast); otherwise "general". Falls back to
    the largest person's spread when the crop follows a body, not a face track.
    """
    crop = d["crops"][0]
    tid = crop.get("track_id")
    if tid is not None:
        spread = _track_x_spread(tf_win, tid)
    else:
        xs = [p["x"] for p in _segment_persons(pf_win)]
        spread = (max(xs) - min(xs)) if xs else 0.0
    return "action" if spread > ACTION_SPREAD else "general"


def reconcile(
    scenes: List[dict],
    tracked_frames: List[dict],
    cuts: List[float],
    src_w: int,
    src_h: int,
    duration: float,
    person_frames: Optional[List[dict]] = None,
    rungs: Optional[List[Tuple[int, int]]] = None,
    text_frames: Optional[List[dict]] = None,
    speaker_segments: Optional[List[dict]] = None,
) -> List[dict]:
    """Build the per-segment crop plan from cuts + Gemini scenes + detections.

    `rungs` is the output canvas's inner-AR ladder (defaults to the 9:16 RUNGS);
    pass RUNGS_BY_CANVAS["3:4"] to plan onto a 3:4 canvas. `text_frames`
    (text_detect.scan_video_text output) supplies the measured wide-text extent.
    `speaker_segments` (Chirp diarization output) supplies the two-person-dialogue
    signal for keep-both / split when no Gemini scene label is present.
    """
    rungs = rungs or RUNGS
    label_map = _global_label_map(tracked_frames)
    scene_starts = [s.get("start_sec", 0.0) for s in scenes]
    bounds = _boundaries(cuts, duration)

    # Build the time indices ONCE; every per-segment window is then a bisect slice
    # of these sorted series rather than a full rescan — keeps the decision loop
    # linear (O(F + B·log F)) instead of quadratic (O(B·F)) in video length.
    persons = person_frames or []
    texts = text_frames or []
    track_times = [f["time_sec"] for f in tracked_frames]
    person_times = [f["time_sec"] for f in persons]
    text_times = [f["time_sec"] for f in texts]

    raw: List[dict] = []
    prev_rung: Optional[Tuple[int, int]] = None
    for start, end in bounds:
        scene = _scene_for(scenes, scene_starts, start, end)
        # When no Gemini scene labels this window as dialogue, fall back to the
        # diarization signal — two speakers taking turns IS a two-person dialogue,
        # which is what unlocks keep-both / split (geometry still gates the layout).
        if not scene.get("scene_type") and _dialogue_in_window(
            speaker_segments or [], start, end
        ):
            scene = {**scene, "scene_type": "dialogue"}
        tf_w = _window(tracked_frames, track_times, start, end)
        pf_w = _window(persons, person_times, start, end)
        d = _decide_segment(
            scene,
            tf_w,
            pf_w,
            _window(texts, text_times, start, end),
            start,
            end,
            label_map,
            src_w,
            src_h,
            rungs,
        )
        if d["layout"] == "split":
            # Split fills the canvas with stacked panels — no rung, and it doesn't
            # disturb letterbox hysteresis (prev_rung carries across untouched).
            trace = _split_decision_trace(d, scene)
            inner_ar = None
        else:
            ideal = pick_rung(d["C"], src_w, src_h, None, rungs)
            inner_ar = pick_rung(d["C"], src_w, src_h, prev_rung, rungs)
            prev_rung = inner_ar
            trace = _decision_trace(d, scene, inner_ar, ideal, src_w, src_h)
        # Pan speed: trust a Gemini scene_type if present (legacy/diagnostic), else
        # derive it from the subject's measured motion across the segment.
        scene_type = scene.get("scene_type") or _motion_scene_type(d, tf_w, pf_w)
        raw.append(
            {
                "start": start,
                "end": end,
                "layout": d["layout"],
                "inner_ar": inner_ar,
                "scene_type": scene_type,
                "crops": d["crops"],
                "reason": trace["trigger"],
                "trace": trace,
                "escalate": d.get("escalate"),
            }
        )

    merged = _merge_short(raw, MIN_DWELL, rungs)
    for seg in merged:
        _attach_focal_points(seg, tracked_frames, track_times, persons, person_times)
        _fill_keypoints(seg)
    return merged


def collect_escalation_points(segments: List[dict]) -> List[dict]:
    """Escalation points emitted by the planner, in time order (drops None).

    Feed to `reframe_escalation.plan_batches` to get the batched gemini-3.5-flash
    requests. Each point carries the segment's deterministic fallback, so a plan
    is renderable whether or not the calls run.
    """
    return [s["escalate"] for s in segments if s.get("escalate")]


def attach_keypoints(segments: List[dict], fps: float) -> List[dict]:
    """Smooth each crop's focal series into pan keypoints (per-segment, scene-bounded).

    Pan velocity/deadzone are chosen per segment from its scene_type, so action
    pans fast and dialogue holds steady. Keypoints are in absolute video time;
    the renderer rebases them per segment.
    """
    from focal_path import smooth_focal_path

    for seg in segments:
        start, end = seg["start"], seg["end"]
        dur = max(0.001, end - start)
        max_velocity, deadzone = SCENE_TYPE_PARAMS.get(
            seg.get("scene_type", ""), DEFAULT_SCENE_PARAMS
        )
        for crop in seg["crops"]:
            pts = crop.get("focal_points") or [
                {"time_sec": start, "x": crop.get("x_target", 0.5), "y": 0.5}
            ]
            xs = [p["x"] for p in pts]
            # ~Static subject → center on the median (robust to boundary jitter),
            # rather than a velocity-limited path that can lock off-center.
            if max(xs) - min(xs) <= STATIC_SPREAD:
                cx = statistics.median(xs)
                cy = statistics.median([p.get("y", 0.5) for p in pts])
                crop["keypoints"] = [(start, cx, cy), (end, cx, cy)]
                continue
            local = [
                {
                    "time_sec": max(0.0, min(dur, p["time_sec"] - start)),
                    "x": p["x"],
                    "y": p.get("y", 0.5),
                }
                for p in pts
            ]
            kl = smooth_focal_path(local, [], dur, fps, max_velocity, deadzone)
            crop["keypoints"] = [(t + start, x, y) for (t, x, y) in kl]
    return segments

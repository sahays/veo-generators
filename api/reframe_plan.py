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

from typing import List, Optional, Tuple

# Rung-ladder math + global Viterbi assignment live in reframe_rungs; the
# per-window signal aggregation (tracks, mouth/speech, text band, focal series)
# in reframe_signals. Both are re-exported here — this module is the planner's
# public face (workers, reframe_decide, reframe_eval and the tests import from
# it), the split is internal organization.
from reframe_rungs import (  # noqa: F401  (re-exported)
    DP_SWITCH_AT_CUT,
    DP_SWITCH_MID_SHOT,
    RUNG_TOLERANCE,
    RUNGS,
    RUNGS_BY_CANVAS,
    assign_rungs,
    pick_rung,
    rung_coverage,
)
from reframe_pan import (  # noqa: F401  (re-exported)
    ACTION_SPREAD,
    DEFAULT_SCENE_PARAMS,
    PAN_CONTAIN_DEFAULT,
    PAN_CONTAIN_FRAC,
    PAN_CONTAIN_MIN,
    PAN_IN_SEC,
    SCENE_TYPE_PARAMS,
    STATIC_SPREAD,
    _motion_scene_type,
    _seed_start_x,
    attach_keypoints,
)
from reframe_points import (  # noqa: F401  (re-exported)
    SIDE_TEXT_MARGIN,
    SUBJECT_AMBIG_RATIO,
    _candidate_facts,
    _candidate_labels,
    _competitors,
    _maybe_graphic_escalation,
    _maybe_speaker_escalation,
    _maybe_subject_escalation,
    _maybe_text_escalation,
    _no_subject_escalation,
    _side_of,
    _text_note,
    _tight_window,
)
from reframe_segments import (  # noqa: F401  (re-exported)
    BOUNDARY_EPS,
    MAX_SEG_LEN,
    MERGE_X_TOL,
    MIN_DWELL,
    _attach_focal_points,
    _boundaries,
    _decision_trace,
    _fill_keypoints,
    _merge_short,
    _seg_has_face,
    _split_decision_trace,
)
from reframe_signals import (  # noqa: F401  (re-exported)
    DIALOGUE_MIN_SPEAK,
    SPEAKER_DOMINANCE,
    SPEAKER_MIN_ACTIVITY,
    SPEAKER_MIN_SAMPLES,
    SPEAKER_TURN_MIN_DWELL,
    STABLE_FRAC,
    TEXT_MIN_FRAMES,
    TEXT_PERSIST_FRAC,
    TEXT_WIDE_MIN,
    _associate_speaker_face,
    _dialogue_in_window,
    _dominant_speaker,
    _global_label_map,
    _hint_x,
    _in_intervals,
    _match_track,
    _scene_for,
    _segment_persons,
    _segment_text_band,
    _segment_track_mouth,
    _speaker_turn_cuts,
    _speech_intervals,
    _stable_tracks,
    _track_series,
    _track_x_spread,
    _window,
    pick_active_speaker,
)

COVERAGE_MARGIN = 0.04  # safety margin added to measured detection width
KEEP_BOTH_SEPARATION = 0.30  # min face-center separation for keep-both
# A single subject can never need full width — cap its coverage demand so a huge
# (foreground / mis-measured) detection doesn't force 16:9 letterbox.
FACE_W_CAP = 0.45  # → at most 1:1 from a single face
PERSON_W_CAP = 0.60  # bodies are wider than faces, but still bounded
# Graphic-vs-subject escalation (decision point #7b): the FaceDetector runs at a
# low min_detection_confidence (0.3) so it doesn't miss real faces — but that also
# lets it fire on logos / title cards / channel bugs (e.g. the SonyLIV title card
# in rf-udcpl2hd: a frac=0.5 "face" on a full-frame graphic). A *false* face like
# that pre-empts the no_subject graphic check and forces a tight crop that slices
# the graphic. So when the SOLE subject is a single LOW-confidence face, the CPU
# can't tell a real person from a graphic — escalate to gemini-3.5-flash (fallback:
# keep the face crop). Calibrated on rf-udcpl2hd: the SonyLIV title-card "face"
# scores ~0.635 and real lead faces ~0.84, so 0.75 sits cleanly between them. Only
# SOLE-face segments use this gate; multi-face shots are unaffected. Erring high
# just asks Gemini more often (fallback is still crop) — Gemini reliably answers
# "crop" for a genuine person and "letterbox" for a graphic.
FACE_CONF_MIN = 0.75

# Equal-prominence framing (product rule): when two or more people are
# comparably PRESENT (frac ratio ≥ SUBJECT_AMBIG_RATIO) and comparably SIZED
# (w ratio ≥ EQUAL_W_RATIO), frame them TOGETHER — a stacked split when its
# gates pass, else one wide keep-both crop that letterboxes as needed — never a
# single-person crop that pushes an equally-important person out of frame.
# This outranks speaker-centering: on rf-udcpl2hd a speaker-centered two-shot
# left the second (equally large) person fully off-frame for 7s. The size gate
# keeps a persistent small background face from counting.
EQUAL_W_RATIO = 0.6

# Vertical-split layout (Phase 3): when two speakers sit too far apart for even a
# 1:1 rung to hold both at a decent size, stack them as two full-canvas panels so
# both read large. Stacking destroys eyeline/spatial continuity, so it is gated
# hard — only a *static, persistent, two-person dialogue* qualifies; everything
# else keeps the single/keep-both crop. left subject → top panel, right → bottom.
SPLIT_MIN_SEPARATION = 0.45  # face-center gap above which 1:1 shrinks both too far
SPLIT_MIN_FRAC = 0.80  # both tracks must be near-continuously present
SPLIT_MIN_DWELL = 3.0  # only for shots that hold long enough to read as intentional
SPLIT_MAX_MOTION = 0.06  # near-static: each track's x-span must stay below this


def _group_crop(group: List[dict]) -> Tuple[dict, float]:
    """The keep-both crop + required span for a group of stable tracks.

    One wide crop centered on the group's extent; `track_ids` lets the eval's
    talker metrics count every member as framed. Shared by the deterministic
    keep-both paths and the Gemini `keep_both` verdict (reframe_decide).
    """
    left = min(s["x"] - s.get("w", 0.0) / 2 for s in group)
    right = max(s["x"] + s.get("w", 0.0) / 2 for s in group)
    span = max(0.0, right - left)
    crop = {
        "track_id": None,
        "track_ids": [s["track_id"] for s in group],
        "x_target": (left + right) / 2,
        "source": "center",
    }
    return crop, span


def _equal_group(stable: List[dict]) -> Optional[List[dict]]:
    """All faces comparably present AND comparably sized to the most-visible one.

    Returns the group (most-visible first, ≥2 members) or None. These people are
    framed TOGETHER (split/keep-both) — see EQUAL_W_RATIO.
    """
    if len(stable) < 2:
        return None
    by_vis = sorted(stable, key=lambda s: -s["frac"])
    top = by_vis[0]
    if top["frac"] <= 0 or top["w"] <= 0:
        return None
    group = [top] + [
        s
        for s in by_vis[1:]
        if s["frac"] / top["frac"] >= SUBJECT_AMBIG_RATIO
        and min(s["w"], top["w"]) / max(s["w"], top["w"]) >= EQUAL_W_RATIO
    ]
    return group if len(group) >= 2 else None


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
# Per-segment decision — the precedence spine (equal-group > speaker pin >
# speaker escalation > keep-both/split > subject pick > person > no-subject)
# ---------------------------------------------------------------------------


def _decide_segment(
    scene,
    tf_win,
    pf_win,
    tx_win,
    start,
    end,
    label_map,
    src_w,
    src_h,
    rungs,
    speech_intervals=None,
    speaker_label=None,
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

    # A single-rung ladder (only the full-bleed rung) can never letterbox, so the
    # letterbox-only escalation kinds (text/no-subject/graphic) would be
    # guaranteed no-ops — don't emit them (or pay Gemini for them). Subject and
    # speaker escalations still apply (a `follow` verdict re-targets the crop).
    # Both shipped canvases (9:16 and 3:4) are multi-rung, so this is True for them.
    can_letterbox = len(rungs) > 1

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
    escalate = (
        _maybe_text_escalation(
            (text_meas, text_span), subj_x, len(stable), src_w, src_h, rungs, start, end
        )
        if can_letterbox
        else None
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
        ids = [s["track_id"] for s in stable]
        mouth = _segment_track_mouth(tf_win, ids)
        faces = _competitors(stable, mouth)
        has_speech = bool(speech_intervals)

        def split_out(split_crops, sep):
            return {
                "layout": "split",
                "crops": split_crops,
                "C": 1.0,  # panels fill the canvas; no rung / letterbox
                "text_meas": round(text_meas, 3),
                "c_meas": round(sep, 3),
                "source": "split",
                "n_faces": len(stable),
                "n_persons": 0,
                "faces": faces,
                # Keep any text escalation: a caption over a split shot is
                # still Gemini's call (a letterbox verdict converts the
                # split back to a full-width single — see apply_verdicts).
                "escalate": escalate,
            }

        # PRODUCT RULE (outranks speaker-centering): two or more equally
        # prominent people are framed TOGETHER — a stacked split when its gates
        # pass, else one wide keep-both crop that letterboxes as needed. A
        # speaker-centered crop of an equal two-shot pushes an equally-important
        # person out of frame; the turn-based re-cut doesn't excuse losing them
        # during the other's turn.
        group = _equal_group(stable)
        if group:
            if len(group) == 2:
                split = _split_crops(group, tf_win, start, end, scene)
                if split:
                    return split_out(split, abs(group[0]["x"] - group[1]["x"]))
            crop, span = _group_crop(group)
            return out("keep_both", crop, span + COVERAGE_MARGIN, span, faces)

        # Speaker-centering for NON-equal shots: in a shot with speech only one
        # person talks at a time and we center them. Pin the speaking FACE by
        # measuring mouth motion over the diarized speech (audio↔face); with no
        # audio, fall back to vision-only mouth motion. A confident speaker →
        # tight centered crop.
        if has_speech:
            speaker_tid = _associate_speaker_face(stable, tf_win, speech_intervals)
        else:
            speaker_tid = pick_active_speaker(mouth)
        if speaker_tid is not None:
            tgt = next(s for s in stable if s["track_id"] == speaker_tid)
            cm = min(tgt["w"], FACE_W_CAP)
            crop = {"track_id": speaker_tid, "x_target": tgt["x"], "source": "speaker"}
            return out("single", crop, cm + COVERAGE_MARGIN, cm, faces)

        # Speech but the CPU couldn't pin the speaker among 2+ faces → ask Gemini.
        # The 1 fps mouth signal can't reliably tell a talking head from a static
        # poster / key art with off-screen narration, so Gemini judges from pixels:
        # center the on-screen speaker (follow), OR keep it wide if it's a graphic
        # with no real talker (letterbox). Fallback follows the most-visible face.
        # Takes precedence over the text-band escalation — but when the two-shot
        # geometry would support keep-both/split, those are OFFERED as verdict
        # options (a shot with speech is exactly when dialogue happens; without
        # this, keep-both/split would be unreachable for real conversations).
        if has_speech and len(stable) >= 2:
            pair = _keep_both_pair(stable, scene)
            if pair is None:
                # For the OFFER the intent gate (dialogue label / sep ≥ 0.45) is
                # unnecessary — Gemini judges intent from the pixels. Geometry
                # still gates: two comparably-present faces far enough apart
                # that a tight single crop would lose one entirely (observed on
                # rf-udcpl2hd: sep ≈ 0.32 left the second person fully out of
                # frame with keep_both never offered).
                by_vis = sorted(stable, key=lambda s: -s["frac"])[:2]
                if abs(by_vis[0]["x"] - by_vis[1]["x"]) >= KEEP_BOTH_SEPARATION:
                    pair = by_vis
            can_split = bool(pair and _split_crops(pair, tf_win, start, end, scene))
            escalate = (
                _maybe_speaker_escalation(
                    stable,
                    start,
                    end,
                    speaker_label,
                    pair=pair,
                    can_split=can_split,
                    text_esc=escalate,
                )
                or escalate
            )
            tgt = max(stable, key=lambda s: s["frac"])
            cm = min(tgt["w"], FACE_W_CAP)
            crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": "face"}
            return out("single", crop, cm + COVERAGE_MARGIN, cm, faces)

        # No speech / no on-screen talker (b-roll, poster, silent group): keep both /
        # stack, or follow one — and let the text-presence letterbox path apply.
        pair = _keep_both_pair(stable, scene)
        if pair:
            # Too far apart for 1:1 to hold both large AND a static dialogue → stack
            # them as panels instead of letterboxing both tiny.
            split = _split_crops(pair, tf_win, start, end, scene)
            if split:
                a, b = pair
                return split_out(split, abs(a["x"] - b["x"]))

            crop, span = _group_crop(pair)
            return out("keep_both", crop, span + COVERAGE_MARGIN, span, faces)

        # Single silent subject pick. Among comparable faces, escalate "which
        # subject?" (#3) and follow the deterministic pick as the fallback.
        fallback_tgt = _match_track(stable, scene, label_map)
        source = "face"
        if len(stable) >= 2:
            tgt = fallback_tgt
            escalate = (
                _maybe_subject_escalation(
                    stable, fallback_tgt, start, end, text_esc=escalate
                )
                or escalate
            )
        else:
            tgt = fallback_tgt
            # A SOLE, low-confidence face may be a logo / title card / graphic the
            # detector hallucinated (#7b). The CPU can't tell — escalate the
            # graphic-vs-subject check to Gemini, unless a Gemini scene hint already
            # named this subject. Fallback follows the face crop (below), so a
            # missing verdict keeps current behaviour.
            if (
                escalate is None
                and can_letterbox
                and tgt.get("conf", 0.5) < FACE_CONF_MIN
                and not scene.get("active_subject")
            ):
                escalate = _maybe_graphic_escalation(
                    tgt, src_w, src_h, rungs, start, end
                )
        cm = min(tgt["w"], FACE_W_CAP)
        crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": source}
        return out("single", crop, cm + COVERAGE_MARGIN, cm, faces)

    # No stable face → try person/body detection. The body's measured width drives
    # the rung directly (unlike a single face, which is capped) — so a wide body
    # already letterboxes to 4:5 / 1:1 / 16:9 as its width grows, no escalation needed.
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
    if escalate is None and can_letterbox:
        escalate = _no_subject_escalation(scene, src_w, src_h, rungs, start, end)
    crop = {"track_id": None, "x_target": _hint_x(scene), "source": "center"}
    return out("single", crop, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Plan assembly
# ---------------------------------------------------------------------------


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
    # Re-cut at speaker turns so a single visual shot re-frames onto whoever is
    # talking (one speaker at a time → keep them centered through the turn).
    turn_cuts = _speaker_turn_cuts(speaker_segments, SPEAKER_TURN_MIN_DWELL)
    bounds = _boundaries(sorted(set(cuts) | set(turn_cuts)), duration)
    # Which boundaries are REAL visual cuts (vs MAX_SEG_LEN subdivisions and
    # speaker-turn re-cuts, which fall mid-shot). attach_keypoints pans across a
    # mid-shot boundary instead of jumping — a hard re-frame with no cut to hide
    # it reads as a jump cut.
    hard_cuts = {c for c in cuts if 0.0 < c < duration}

    # Build the time indices ONCE; every per-segment window is then a bisect slice
    # of these sorted series rather than a full rescan — keeps the decision loop
    # linear (O(F + B·log F)) instead of quadratic (O(B·F)) in video length.
    persons = person_frames or []
    texts = text_frames or []
    track_times = [f["time_sec"] for f in tracked_frames]
    person_times = [f["time_sec"] for f in persons]
    text_times = [f["time_sec"] for f in texts]

    # Pass 1: per-cell content decisions (layout, subject, required coverage).
    decided: List[dict] = []
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
            _speech_intervals(speaker_segments, start, end),
            _dominant_speaker(speaker_segments, start, end),
        )
        decided.append(
            {
                "start": start,
                "end": end,
                "scene": scene,
                "d": d,
                "tf_w": tf_w,
                "pf_w": pf_w,
                "starts_at_cut": start == 0.0 or start in hard_cuts,
            }
        )

    # Pass 2: globally-optimal rung sequence (Viterbi DP over the whole video).
    chosen = assign_rungs(
        [
            {
                "C": c["d"]["C"],
                "dur": c["end"] - c["start"],
                "starts_at_cut": c["starts_at_cut"],
                "split": c["d"]["layout"] == "split",
            }
            for c in decided
        ],
        src_w,
        src_h,
        rungs,
    )

    raw: List[dict] = []
    for c, inner_ar in zip(decided, chosen):
        d, scene = c["d"], c["scene"]
        if d["layout"] == "split":
            trace = _split_decision_trace(d, scene)
            inner_ar = None
        else:
            ideal = pick_rung(d["C"], src_w, src_h, rungs)
            trace = _decision_trace(d, scene, inner_ar, ideal, src_w, src_h)
        # Pan speed: trust a Gemini scene_type if present (legacy/diagnostic), else
        # derive it from the subject's measured motion across the segment.
        scene_type = scene.get("scene_type") or _motion_scene_type(
            d, c["tf_w"], c["pf_w"]
        )
        raw.append(
            {
                "start": c["start"],
                "end": c["end"],
                "layout": d["layout"],
                "inner_ar": inner_ar,
                "scene_type": scene_type,
                "crops": d["crops"],
                "reason": trace["trigger"],
                "trace": trace,
                "escalate": d.get("escalate"),
                "starts_at_cut": c["starts_at_cut"],
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

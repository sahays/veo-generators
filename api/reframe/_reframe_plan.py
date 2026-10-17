"""Reframe v2 decision layer — turn detections into a per-segment crop plan.

Pure logic: no I/O, no cv2/ffmpeg. Segments come from scene cuts (subdivided so a
long take is re-decided periodically); per segment it chooses an inner aspect ratio
(how much to crop vs. letterbox) and which subject(s) to follow, from MediaPipe face
/ person tracks, a CPU-measured wide-text band, and an optional diarization dialogue
signal.
"""

from typing import Any, List, Optional, Tuple

from reframe_pan import (  # noqa: F401
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
from reframe_plan_helpers import (  # noqa: F401
    COVERAGE_MARGIN,
    EQUAL_MIN_W,
    EQUAL_PROM_RATIO,
    EQUAL_W_RATIO,
    FACE_CONF_MIN,
    FACE_W_CAP,
    KEEP_BOTH_SEPARATION,
    PERSON_W_CAP,
    SPLIT_MAX_MOTION,
    SPLIT_MIN_DWELL,
    SPLIT_MIN_FRAC,
    SPLIT_MIN_SEPARATION,
    _decide_with_stable_faces,
    _equal_group,
    _group_crop,
    _keep_both_pair,
    _make_seg_out,
    _split_crops,
)
from reframe_points import (  # noqa: F401
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
from reframe_rungs import (  # noqa: F401
    DP_SWITCH_AT_CUT,
    DP_SWITCH_MID_SHOT,
    RUNG_TOLERANCE,
    RUNGS,
    RUNGS_BY_CANVAS,
    assign_rungs,
    pick_rung,
    rung_coverage,
)
from reframe_segments import (  # noqa: F401
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
from reframe_semantic import GRAPHIC_KINDS as SEMANTIC_GRAPHIC_KINDS
from reframe_signals import (  # noqa: F401
    DIALOGUE_MIN_SPEAK,
    PROM_SPEAK_MULT,
    SPEAKER_DOMINANCE,
    SPEAKER_MIN_ACTIVITY,
    SPEAKER_MIN_SAMPLES,
    SPEAKER_TURN_MIN_DWELL,
    STABLE_FRAC,
    TEXT_MIN_FRAMES,
    TEXT_PERSIST_FRAC,
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
    _segment_text_regions,
    _segment_track_mouth,
    _semantic_speaker_position,
    _speaker_turn_cuts,
    _speech_intervals,
    _stable_tracks,
    _track_series,
    _track_x_spread,
    _window,
    pick_active_speaker,
    prominence,
)
from text_detect import persistent_text_regions


def _initial_subj_x(
    stable: List[dict], pf_win: List[dict], tf_win: List[dict], scene: dict
) -> Tuple[float, Optional[float]]:
    subj_hint = _hint_x(scene) if scene.get("active_subject") else None
    if stable:
        return max(stable, key=lambda s: (prominence(s), -abs(s["x"] - 0.5)))[
            "x"
        ], subj_hint
    persons = _segment_persons(pf_win, tf_win, hint_x=subj_hint)
    if persons and len(persons) / max(1, len(pf_win)) >= STABLE_FRAC:
        return sum(p["x"] for p in persons) / len(persons), subj_hint
    return _hint_x(scene), subj_hint


def _decide_segment(
    scene: dict,
    tf_win: List[dict],
    pf_win: List[dict],
    tx_win: List[dict],
    start: float,
    end: float,
    label_map: dict,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
    speech_intervals: Optional[List[Tuple[float, float]]] = None,
    speaker_label: Optional[str] = None,
    text_regions: Optional[List[dict]] = None,
    has_diarization: bool = False,
) -> dict:
    """Decide layout, focal target and required coverage for one segment."""
    stable = _stable_tracks(tf_win)
    text_meas, text_span, seg_regions = _segment_text_regions(tx_win, text_regions)
    semantic = bool(scene.get("content_kind"))
    text_keep = scene.get("text_keep") if semantic else None
    can_letterbox = len(rungs) > 1
    subj_x, subj_hint = _initial_subj_x(stable, pf_win, tf_win, scene)
    escalate = (
        _maybe_text_escalation(
            (text_meas, text_span),
            subj_x,
            len(stable),
            src_w,
            src_h,
            rungs,
            start,
            end,
            regions=seg_regions,
        )
        if can_letterbox and not semantic
        else None
    )
    if semantic and scene.get("content_kind") in SEMANTIC_GRAPHIC_KINDS:
        c = (
            min(
                1.0,
                2.0 * max(0.5 - text_keep["band"][0], text_keep["band"][1] - 0.5)
                + COVERAGE_MARGIN,
            )
            if text_keep
            else 1.0
        )
        return _make_seg_out(
            "single",
            {"track_id": None, "x_target": 0.5, "source": "semantic_graphic"},
            c,
            c,
            text_meas,
            len(stable),
            escalate,
            text_keep,
        )
    if stable:
        return _decide_with_stable_faces(
            stable,
            tf_win,
            scene,
            label_map,
            start,
            end,
            src_w,
            src_h,
            rungs,
            speech_intervals,
            speaker_label,
            has_diarization,
            can_letterbox,
            semantic,
            escalate,
            text_meas,
            text_keep,
        )
    persons = _segment_persons(pf_win, tf_win, hint_x=subj_hint)
    if persons and len(persons) / max(1, len(pf_win)) >= STABLE_FRAC:
        mean_x = sum(p["x"] for p in persons) / len(persons)
        mean_w = min(sum(p["w"] for p in persons) / len(persons), PERSON_W_CAP)
        return _make_seg_out(
            "single",
            {"track_id": None, "x_target": mean_x, "source": "person"},
            mean_w + COVERAGE_MARGIN,
            mean_w,
            text_meas,
            0,
            escalate,
            text_keep,
            n_persons=len(persons),
        )
    if escalate is None and can_letterbox and not semantic:
        escalate = _no_subject_escalation(scene, src_w, src_h, rungs, start, end)
    return _make_seg_out(
        "single",
        {"track_id": None, "x_target": _hint_x(scene), "source": "center"},
        0.0,
        0.0,
        text_meas,
        0,
        escalate,
        text_keep,
    )


def _decide_all_windows(
    bounds: List[Tuple[float, float]],
    scenes: List[dict],
    scene_starts: List[float],
    tracked_frames: List[dict],
    track_times: List[float],
    persons: List[dict],
    person_times: List[float],
    texts: List[dict],
    text_times: List[float],
    label_map: dict,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
    speaker_segments: Optional[List[dict]],
    text_regions: Optional[List[dict]],
    hard_cuts: set,
) -> List[dict]:
    decided: List[dict] = []
    for start, end in bounds:
        scene = _scene_for(scenes, scene_starts, start, end)
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
            text_regions=text_regions,
            has_diarization=bool(speaker_segments),
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
    return decided


def _assemble_raw_segments(
    decided: List[dict],
    chosen: List[Any],
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
) -> List[dict]:
    raw: List[dict] = []
    for c, inner_ar in zip(decided, chosen):
        d, scene = c["d"], c["scene"]
        if d["layout"] == "split":
            trace = _split_decision_trace(d, scene)
            inner_ar = None
        else:
            ideal = pick_rung(d["C"], src_w, src_h, rungs)
            trace = _decision_trace(d, scene, inner_ar, ideal, src_w, src_h)
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
    return raw


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
    """Build the per-segment crop plan from cuts + Gemini scenes + detections."""
    rungs = rungs or RUNGS
    label_map = _global_label_map(tracked_frames)
    scene_starts = [s.get("start_sec", 0.0) for s in scenes]
    turn_cuts = _speaker_turn_cuts(speaker_segments, SPEAKER_TURN_MIN_DWELL)
    bounds = _boundaries(sorted(set(cuts) | set(turn_cuts)), duration)
    hard_cuts = {c for c in cuts if 0.0 < c < duration}
    persons = person_frames or []
    texts = text_frames or []
    track_times = [f["time_sec"] for f in tracked_frames]
    person_times = [f["time_sec"] for f in persons]
    text_times = [f["time_sec"] for f in texts]
    text_regions = persistent_text_regions(texts)
    decided = _decide_all_windows(
        bounds,
        scenes,
        scene_starts,
        tracked_frames,
        track_times,
        persons,
        person_times,
        texts,
        text_times,
        label_map,
        src_w,
        src_h,
        rungs,
        speaker_segments,
        text_regions,
        hard_cuts,
    )
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
    raw = _assemble_raw_segments(decided, chosen, src_w, src_h, rungs)
    merged = _merge_short(raw, MIN_DWELL, rungs)
    for seg in merged:
        _attach_focal_points(seg, tracked_frames, track_times, persons, person_times)
        _fill_keypoints(seg)
    return merged


def collect_escalation_points(segments: List[dict]) -> List[dict]:
    """Escalation points emitted by the planner, in time order (drops None)."""
    return [s["escalate"] for s in segments if s.get("escalate")]

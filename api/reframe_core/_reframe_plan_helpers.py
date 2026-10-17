"""Helper functions and constants for reframe_plan decision and layout logic."""

from typing import Any, List, Optional, Tuple

from reframe_points import (
    _competitors,
    _maybe_graphic_escalation,
    _maybe_speaker_escalation,
    _maybe_subject_escalation,
)
from reframe_signals import (
    PROM_SPEAK_MULT,
    _associate_speaker_face,
    _match_track,
    _segment_track_mouth,
    _semantic_speaker_position,
    _track_x_spread,
    pick_active_speaker,
    prominence,
)

COVERAGE_MARGIN = 0.04
KEEP_BOTH_SEPARATION = 0.30
FACE_W_CAP = 0.45
PERSON_W_CAP = 0.60
FACE_CONF_MIN = 0.75

EQUAL_PROM_RATIO = 0.75
EQUAL_W_RATIO = 0.6
EQUAL_MIN_W = 0.05

SPLIT_MIN_SEPARATION = 0.45
SPLIT_MIN_FRAC = 0.80
SPLIT_MIN_DWELL = 3.0
SPLIT_MAX_MOTION = 0.06


def _group_crop(group: List[dict]) -> Tuple[dict, float]:
    """The keep-both crop + required span for a group of stable tracks."""
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
    """All faces comparably PROMINENT to the leading one."""
    if len(stable) < 2:
        return None
    ranked = sorted(stable, key=prominence, reverse=True)
    top = ranked[0]
    top_prom = prominence(top)
    if top_prom <= 0 or top["w"] <= 0:
        return None
    group = [top] + [
        s
        for s in ranked[1:]
        if prominence(s) / top_prom >= EQUAL_PROM_RATIO and s["w"] >= EQUAL_MIN_W
    ]
    return group if len(group) >= 2 else None


def _keep_both_pair(stable: List[dict], scene: dict) -> Optional[List[dict]]:
    """Return the two far-apart tracks to keep, or None for a single-subject crop."""
    if len(stable) < 2:
        return None
    layout = (scene.get("layout") or "").lower()
    by_vis = sorted(stable, key=prominence, reverse=True)[:2]
    sep = abs(by_vis[0]["x"] - by_vis[1]["x"])
    wants_both = layout == "side_by_side" or scene.get("scene_type") == "dialogue"
    if sep >= KEEP_BOTH_SEPARATION and (wants_both or sep >= 0.45):
        return by_vis
    return None


def _split_crops(
    pair: List[dict], win: List[dict], start: float, end: float, scene: dict
) -> Optional[List[dict]]:
    """Two stacked panels for a static, far-apart two-person dialogue, or None."""
    a, b = pair
    if abs(a["x"] - b["x"]) < SPLIT_MIN_SEPARATION:
        return None
    if min(a["frac"], b["frac"]) < SPLIT_MIN_FRAC or (end - start) < SPLIT_MIN_DWELL:
        return None
    layout = (scene.get("layout") or "").lower()
    if scene.get("scene_type") != "dialogue" and layout != "side_by_side":
        return None
    left, right = sorted(pair, key=lambda s: s["x"])
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


def _make_seg_out(
    layout: str,
    crop: dict,
    c: float,
    c_meas: float,
    text_meas: float,
    n_faces: int,
    escalate: Optional[dict],
    text_keep: Optional[dict],
    faces: Optional[List[dict]] = None,
    n_persons: int = 0,
) -> dict:
    d: dict = {
        "layout": layout,
        "crops": [crop],
        "C": min(1.0, c),
        "text_meas": round(text_meas, 3),
        "c_meas": round(c_meas, 3),
        "source": crop["source"],
        "n_faces": n_faces,
        "n_persons": n_persons,
        "faces": faces or [],
        "escalate": escalate,
    }
    if text_keep and layout != "split":
        b0, b1 = text_keep["band"]
        cx = crop.get("x_target") or 0.5
        req = 2.0 * max(cx - b0, b1 - cx) + COVERAGE_MARGIN
        if req > d["C"]:
            d["C"] = min(1.0, req)
            d["text_keep"] = [round(b0, 3), round(b1, 3)]
            d["text_low_confidence"] = bool(text_keep.get("low_confidence"))
    return d


def _make_split_out(
    split_crops: List[dict],
    sep: float,
    text_meas: float,
    n_faces: int,
    faces: List[dict],
    escalate: Optional[dict],
) -> dict:
    return {
        "layout": "split",
        "crops": split_crops,
        "C": 1.0,
        "text_meas": round(text_meas, 3),
        "c_meas": round(sep, 3),
        "source": "split",
        "n_faces": n_faces,
        "n_persons": 0,
        "faces": faces,
        "escalate": escalate,
    }


def _resolve_speaker_tid(
    stable: List[dict],
    tf_win: List[dict],
    scene: dict,
    label_map: dict,
    mouth: dict,
    speech_intervals: Optional[List[Tuple[float, float]]],
    speaker_label: Optional[str],
    semantic: bool,
    has_diarization: bool,
) -> Tuple[Optional[Any], Optional[str]]:
    sem_pos = _semantic_speaker_position(scene, speaker_label) if semantic else None
    if sem_pos == "offscreen":
        return None, sem_pos
    if speech_intervals:
        speaker_tid = _associate_speaker_face(stable, tf_win, speech_intervals)
        if speaker_tid is None and sem_pos in ("left", "center", "right"):
            speaker_tid = _match_track(stable, {"active_subject": sem_pos}, label_map)[
                "track_id"
            ]
        return speaker_tid, sem_pos
    if not has_diarization:
        return pick_active_speaker(mouth), sem_pos
    return None, sem_pos


def _decide_speech_multi_face(
    stable: List[dict],
    tf_win: List[dict],
    scene: dict,
    start: float,
    end: float,
    speaker_label: Optional[str],
    escalate: Optional[dict],
    text_meas: float,
    text_keep: Optional[dict],
    faces: List[dict],
) -> dict:
    pair = _keep_both_pair(stable, scene)
    if pair is None:
        by_vis = sorted(stable, key=prominence, reverse=True)[:2]
        if abs(by_vis[0]["x"] - by_vis[1]["x"]) >= KEEP_BOTH_SEPARATION:
            pair = by_vis
    can_split = bool(pair and _split_crops(pair, tf_win, start, end, scene))
    esc = (
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
    tgt = max(stable, key=prominence)
    cm = min(tgt["w"], FACE_W_CAP)
    crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": "face"}
    return _make_seg_out(
        "single",
        crop,
        cm + COVERAGE_MARGIN,
        cm,
        text_meas,
        len(stable),
        esc,
        text_keep,
        faces,
    )


def _decide_silent_faces(
    stable: List[dict],
    tf_win: List[dict],
    scene: dict,
    label_map: dict,
    start: float,
    end: float,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
    can_letterbox: bool,
    semantic: bool,
    escalate: Optional[dict],
    text_meas: float,
    text_keep: Optional[dict],
    faces: List[dict],
) -> dict:
    pair = _keep_both_pair(stable, scene)
    if pair:
        split = _split_crops(pair, tf_win, start, end, scene)
        if split:
            return _make_split_out(
                split,
                abs(pair[0]["x"] - pair[1]["x"]),
                text_meas,
                len(stable),
                faces,
                escalate,
            )
        crop, span = _group_crop(pair)
        return _make_seg_out(
            "keep_both",
            crop,
            span + COVERAGE_MARGIN,
            span,
            text_meas,
            len(stable),
            escalate,
            text_keep,
            faces,
        )
    tgt = _match_track(stable, scene, label_map)
    esc = escalate
    if len(stable) >= 2:
        esc = (
            _maybe_subject_escalation(stable, tgt, start, end, text_esc=escalate)
            or escalate
        )
    elif (
        esc is None
        and can_letterbox
        and not semantic
        and tgt.get("conf", 0.5) < FACE_CONF_MIN
        and not scene.get("active_subject")
    ):
        esc = _maybe_graphic_escalation(tgt, src_w, src_h, rungs, start, end)
    cm = min(tgt["w"], FACE_W_CAP)
    crop = {"track_id": tgt["track_id"], "x_target": tgt["x"], "source": "face"}
    return _make_seg_out(
        "single",
        crop,
        cm + COVERAGE_MARGIN,
        cm,
        text_meas,
        len(stable),
        esc,
        text_keep,
        faces,
    )


def _decide_with_stable_faces(
    stable: List[dict],
    tf_win: List[dict],
    scene: dict,
    label_map: dict,
    start: float,
    end: float,
    src_w: int,
    src_h: int,
    rungs: List[Tuple[int, int]],
    speech_intervals: Optional[List[Tuple[float, float]]],
    speaker_label: Optional[str],
    has_diarization: bool,
    can_letterbox: bool,
    semantic: bool,
    escalate: Optional[dict],
    text_meas: float,
    text_keep: Optional[dict],
) -> dict:
    ids = [s["track_id"] for s in stable]
    mouth = _segment_track_mouth(tf_win, ids)
    faces = _competitors(stable, mouth)
    speaker_tid, sem_pos = _resolve_speaker_tid(
        stable,
        tf_win,
        scene,
        label_map,
        mouth,
        speech_intervals,
        speaker_label,
        semantic,
        has_diarization,
    )
    group = _equal_group(stable)
    if group:
        if len(group) == 2:
            split = _split_crops(group, tf_win, start, end, scene)
            if split:
                return _make_split_out(
                    split,
                    abs(group[0]["x"] - group[1]["x"]),
                    text_meas,
                    len(stable),
                    faces,
                    escalate,
                )
        crop, span = _group_crop(group)
        return _make_seg_out(
            "keep_both",
            crop,
            span + COVERAGE_MARGIN,
            span,
            text_meas,
            len(stable),
            escalate,
            text_keep,
            faces,
        )
    if speaker_tid is not None:
        for s in stable:
            if s["track_id"] == speaker_tid:
                s["speak_mult"] = PROM_SPEAK_MULT
                s["prom"] = round(s.get("prom", s["frac"]) * PROM_SPEAK_MULT, 4)
        tgt = next(s for s in stable if s["track_id"] == speaker_tid)
        cm = min(tgt["w"], FACE_W_CAP)
        crop = {"track_id": speaker_tid, "x_target": tgt["x"], "source": "speaker"}
        return _make_seg_out(
            "single",
            crop,
            cm + COVERAGE_MARGIN,
            cm,
            text_meas,
            len(stable),
            escalate,
            text_keep,
            faces,
        )
    if speech_intervals and len(stable) >= 2 and sem_pos != "offscreen":
        return _decide_speech_multi_face(
            stable,
            tf_win,
            scene,
            start,
            end,
            speaker_label,
            escalate,
            text_meas,
            text_keep,
            faces,
        )
    return _decide_silent_faces(
        stable,
        tf_win,
        scene,
        label_map,
        start,
        end,
        src_w,
        src_h,
        rungs,
        can_letterbox,
        semantic,
        escalate,
        text_meas,
        text_keep,
        faces,
    )

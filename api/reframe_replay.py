"""Deterministic replay of a captured reframe job — the regression harness core.

A fixture (built by ``api/scripts/build-reframe-fixture.py`` from the
``detections.json.gz`` every production job now dumps) carries the raw pipeline
inputs: probe, cuts, per-frame detections, text frames, speaker segments, plus
the job's stored plan (whose ``escalate.verdict`` entries let Pass-2 replay
without calling Gemini). Everything downstream of detection is pure logic
(no I/O, no cv2, no network), so CI can re-run planning + verdict application +
eval on real production inputs and gate metric drift between code changes.

Used by ``api/tests/test_reframe_regression.py`` (delta gates vs committed
baselines) and ``build-reframe-fixture.py --verify/--rebaseline``.
"""

from typing import List, Optional

from mediapipe_detection import track_faces
from reframe_decide import apply_verdicts, harmonize_letterbox
from reframe_escalation import cluster_escalations
from reframe_eval import evaluate
from reframe_filters import OUTPUT_CANVAS
from reframe_plan import (
    RUNGS_BY_CANVAS,
    attach_keypoints,
    collect_escalation_points,
    reconcile,
)


def recorded_verdicts(stored_plan: Optional[List[dict]]) -> List[dict]:
    """Extract the Gemini verdicts a production run actually applied.

    ``apply_verdicts`` matches verdicts to segments by ``cluster_key`` (falling
    back to ``key``), and each stored verdict carries its own ``key`` — so
    feeding these back reproduces Pass 2 exactly, no model call needed.
    """
    seen = {}
    for seg in stored_plan or []:
        verdict = (seg.get("escalate") or {}).get("verdict")
        if verdict and verdict.get("key"):
            seen.setdefault(verdict["key"], verdict)
    return list(seen.values())


def replay(fixture: dict) -> dict:
    """Re-run the pure pipeline on captured inputs.

    Returns ``{"segments": [...], "report": {...}}`` — the reconciled plan
    (post-verdicts, post-keypoints) and its eval report.
    """
    probe = fixture["probe"]
    # Detections in a fixture with an active_area rect are normalized to the
    # ACTIVE picture (baked bars trimmed) — plan in those dims, like the worker.
    from reframe_active_area import rect_px

    _ax, _ay, w, h = rect_px(
        fixture.get("active_area"), probe["width"], probe["height"]
    )
    dur, fps = probe["duration"], probe["fps"]
    canvas = fixture.get("canvas") or "9:16"
    rungs = RUNGS_BY_CANVAS.get(canvas, RUNGS_BY_CANVAS["9:16"])
    _, out_h = OUTPUT_CANVAS.get(canvas, OUTPUT_CANVAS["9:16"])

    det_frames = fixture["det_frames"]
    tracked_frames = track_faces(
        [{"time_sec": f["time_sec"], "faces": f["faces"]} for f in det_frames],
        cuts=fixture["cuts"],
    )
    person_frames = [
        {"time_sec": f["time_sec"], "persons": f["persons"]} for f in det_frames
    ]

    segments = reconcile(
        [],
        tracked_frames,
        fixture["cuts"],
        w,
        h,
        dur,
        person_frames=person_frames,
        rungs=rungs,
        text_frames=fixture.get("text_frames"),
        speaker_segments=fixture.get("speaker_segments"),
    )
    verdicts = recorded_verdicts(fixture.get("stored_plan"))
    if verdicts:
        # Recorded verdicts carry CLUSTER keys (`<key>#t<start>`); the freshly
        # planned segments' escalate dicts only carry point keys until
        # cluster_escalations stamps `cluster_key` on them — without this,
        # apply_verdicts matches nothing and every verdict is silently dropped.
        cluster_escalations(collect_escalation_points(segments))
        apply_verdicts(segments, verdicts, w, h, rungs, tracked_frames, person_frames)
        harmonize_letterbox(segments, w, h, rungs)
    attach_keypoints(segments, fps, w, h)

    report = evaluate(
        segments,
        tracked_frames,
        person_frames,
        fixture.get("speaker_segments"),
        w,
        h,
        dur,
        canvas_h=out_h,
        rungs=rungs,
    )
    return {"segments": segments, "report": report}


def plan_metrics(segments: List[dict], report: dict) -> dict:
    """The gated metric set — one flat dict per fixture, stored in baselines.json."""
    lb = report.get("letterbox") or {}
    talker = report.get("talker") or {}
    stability = report.get("stability") or {}
    meta = report.get("meta") or {}
    return {
        "segments": len(segments),
        "face_cut_rate": lb.get("face_cut_rate"),
        "over_letterbox_rate": lb.get("over_letterbox_rate"),
        "mean_letterbox_pct": lb.get("mean_letterbox_pct"),
        "framed_speaker_active_rate": talker.get("framed_speaker_active_rate"),
        "crop_jumps_per_min": stability.get("crop_jumps_per_min"),
        "ar_changes_per_min": stability.get("ar_changes_per_min"),
        "center_crop_segments": meta.get("center_crop_segments"),
        "speaker_segments": meta.get("speaker_segments"),
        "letterbox_16x9_segments": meta.get("letterbox_16x9_segments"),
        "split_segments": meta.get("split_segments"),
    }


def compact_plan(segments: List[dict]) -> List[dict]:
    """The comparable shape of a plan — mirrors what the worker persists."""
    return [
        {
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "layout": s["layout"],
            "inner_ar": list(s["inner_ar"]) if s["inner_ar"] else None,
            "reason": s.get("reason", ""),
        }
        for s in segments
    ]

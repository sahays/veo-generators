"""Reframe observability, fixture dumping, and evaluation reporting helpers."""

from collections import Counter
import gzip
import json
import logging
from typing import Any, Optional

import deps

logger = logging.getLogger(__name__)


def dump_detection_fixture(
    record_id: str,
    probe: dict,
    canvas: str,
    cuts: list,
    det_frames: list,
    text_frames: list,
    speaker_segments: list,
    sample_fps: float,
    active_area: Any = None,
) -> None:
    """Persist the raw pipeline inputs to GCS (gzipped JSON) for replay testing."""
    try:
        payload = {
            "record_id": record_id,
            "canvas": canvas,
            "sample_fps": sample_fps,
            "probe": {
                k: probe.get(k)
                for k in ("width", "height", "duration", "fps", "has_audio")
            },
            "active_area": active_area,
            "cuts": cuts,
            "det_frames": det_frames,
            "text_frames": text_frames,
            "speaker_segments": speaker_segments,
        }
        data = gzip.compress(json.dumps(payload, default=float).encode("utf-8"))
        uri = deps.storage_svc.upload_bytes(
            data,
            f"reframes/{record_id}/detections.json.gz",
            content_type="application/gzip",
        )
        logger.info(
            f"[reframe:{record_id}] detection fixture: {uri} ({len(data) // 1024} KiB)",
            extra={
                "who": "reframe",
                "where": "dump_detection_fixture",
                "what": uri,
                "why": "replay_fixture",
                "how": "upload_bytes",
            },
        )
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] fixture dump skipped ({e})",
            extra={
                "who": "reframe",
                "where": "dump_detection_fixture",
                "what": "dump_skipped",
                "why": str(e),
                "how": "ignore_error",
            },
        )


def _compact_segments(segments: list[dict]) -> list[dict]:
    """Build compact per-segment decision records for Firestore storage."""
    return [
        {
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "layout": s["layout"],
            "inner_ar": list(s["inner_ar"]) if s["inner_ar"] else None,
            "reason": s.get("reason", ""),
            "trace": s.get("trace"),
            "escalate": s.get("escalate"),
            "starts_at_cut": s.get("starts_at_cut"),
        }
        for s in segments
    ]


def _count_letterbox_reasons(segments: list[dict]) -> dict[str, int]:
    """Count why 16:9 letterboxing occurred across segments."""
    why16: Counter[str] = Counter()
    for s in segments:
        if s["inner_ar"] is None or tuple(s["inner_ar"]) != (16, 9):
            continue
        tr = s.get("trace", {})
        if tr.get("layout") == "keep_both":
            why16["two-face span"] += 1
        elif tr.get("source") == "semantic_graphic" or tr.get("text_keep"):
            why16["semantic text/graphic"] += 1
        elif tr.get("source") in ("gemini_text", "gemini_graphic"):
            why16["gemini text/graphic"] += 1
        else:
            why16["wide subject"] += 1
    return dict(why16)


def _build_plan_summary(
    segments: list[dict], semantic_status: str, active_area: Any
) -> dict[str, Any]:
    """Build aggregate observability summary for a segment plan."""
    from reframe_escalation import plan_batches
    from reframe_plan import collect_escalation_points

    ar = Counter(
        "split" if s["inner_ar"] is None else f"{s['inner_ar'][0]}:{s['inner_ar'][1]}"
        for s in segments
    )
    src = Counter(s.get("trace", {}).get("source") for s in segments)
    batch = plan_batches(collect_escalation_points(segments))
    hyst = sum(1 for s in segments if s.get("trace", {}).get("hysteresis"))
    txt_keep = sum(1 for s in segments if s.get("trace", {}).get("text_keep"))
    return {
        "segments": len(segments),
        "aspect_ratios": dict(ar),
        "sources": dict(src),
        "letterbox_16x9_reasons": _count_letterbox_reasons(segments),
        "hysteresis_segments": hyst,
        "speaker_segments": src.get("speaker", 0),
        "split_segments": sum(1 for s in segments if s["layout"] == "split"),
        "semantic": {"status": semantic_status, "text_keep_segments": txt_keep},
        "active_area": active_area,
        "full_frame_segments": sum(1 for s in segments if s.get("src_full_frame")),
        "escalations": {
            "n_points": batch["n_points"],
            "n_clusters": batch["n_clusters"],
            "n_calls": batch["n_calls"],
            "dropped": len(batch["dropped"]),
        },
    }


def store_segment_plan(
    record_id: str,
    segments: list[dict],
    semantic_status: str = "off",
    active_area: Any = None,
) -> None:
    """Persist the per-segment decision trace and a run summary."""
    compact = _compact_segments(segments)
    summary = _build_plan_summary(segments, semantic_status, active_area)
    deps.firestore_svc.update_reframe_record(
        record_id, {"segment_plan": compact, "reframe_summary": summary}
    )


def store_eval_report(
    record_id: str,
    segments: list[dict],
    tracked_frames: list,
    person_frames: list,
    speaker_segments: list,
    src_w: int,
    src_h: int,
    duration: float,
    canvas_h: int = 1920,
    rungs: Any = None,
    perception: Optional[dict] = None,
) -> Optional[dict]:
    """Compute and store reference-free quality report card before render."""
    try:
        from reframe_eval import evaluate

        speech = [
            {"start_sec": s.get("start_sec"), "end_sec": s.get("end_sec")}
            for s in (speaker_segments or [])
        ]
        report = evaluate(
            segments,
            tracked_frames,
            person_frames,
            speech,
            src_w,
            src_h,
            duration,
            canvas_h=canvas_h,
            rungs=rungs,
            perception=perception,
        )
        if not report:
            return None
        report.setdefault("meta", {}).update({"src_w": src_w, "src_h": src_h})
        deps.firestore_svc.update_reframe_record(record_id, {"eval_report": report})
        lb, talker = report["letterbox"], report.get("talker") or {}
        failing = report.get("failing") or []
        fail_str = (
            " failing=" + ",".join(f"{f['metric']}:{f['value']}" for f in failing)
            if failing
            else ""
        )
        logger.info(
            f"[reframe:{record_id}] eval: overall={report['overall']} face_cut={lb['face_cut_rate']} over_lb={lb['over_letterbox_rate']} av_sync={talker.get('av_sync_score')} miss={talker.get('speaker_miss_rate')}{fail_str}",
            extra={
                "who": "reframe",
                "where": "store_eval_report",
                "what": f"overall={report['overall']}",
                "why": "quality_eval",
                "how": "evaluate",
            },
        )
        return report
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] eval skipped ({e})",
            extra={
                "who": "reframe",
                "where": "store_eval_report",
                "what": "eval_skipped",
                "why": str(e),
                "how": "return_none",
            },
        )
        return None


def store_render_check(
    record_id: str,
    report: Optional[dict],
    out_path: str,
    segments: list[dict],
    src_w: int,
    src_h: int,
    out_w: int,
    out_h: int,
) -> None:
    """Sampled OUTPUT-pixel validation (runs after render). Best-effort."""
    try:
        from reframe_eval import _rollup
        from reframe_render_check import check_render

        block = check_render(out_path, segments, src_w, src_h, out_w, out_h)
        if not block:
            return
        if report is not None:
            report["render"] = block
            report["overall"] = _rollup(
                report.get("overall", "na"), block.get("flag", "na")
            )
            update = {"eval_report": report}
        else:
            update = {"eval_report": {"render": block, "overall": block["flag"]}}
        deps.firestore_svc.update_reframe_record(record_id, update)
        logger.info(
            f"[reframe:{record_id}] render-check: {block['flag']} nonblank={block['nonblank_rate']} face={block.get('face_present_rate')} panels={block.get('split_panel_fill_rate')}",
            extra={
                "who": "reframe",
                "where": "store_render_check",
                "what": f"flag={block['flag']}",
                "why": "render_validation",
                "how": "check_render",
            },
        )
    except Exception as e:
        logger.warning(
            f"[reframe:{record_id}] render-check skipped ({e})",
            extra={
                "who": "reframe",
                "where": "store_render_check",
                "what": "render_check_skipped",
                "why": str(e),
                "how": "ignore_error",
            },
        )

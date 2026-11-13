"""Engagement job: relate a scene analysis timeline to an engagement signal.

A job waits until the scene analysis it links to is `completed`; see
`get_pending_records`. Stages (see `StagedJobProcessor` for the job loop and
checkpoint helpers):

1. `signal`: build the curve. A template is generated from the video duration
   and seeded with the record id, so the same record always gets the same
   curve; a BARC CSV is downloaded and parsed. Checkpoint: `signal.json`.
2. `stats`: read the analysis's `timeline.json` and compute every number in
   the report. Deterministic and cheap, so it is recomputed on a retry.
3. `explain`: one model call that describes all peaks, valleys and drops.
   Checkpoint: `explain.json`.
4. `recommend`: one model call for the recommendations, then `report.json`
   is written. Checkpoint: `recommend.json`.

The model only supplies prose. A model call that fails or returns nothing
usable does not fail the job: the report keeps its numbers, the prose stays
empty and the record notes it in `stage_detail`. Model answers are
checkpointed with a digest of their prompt, so a retried job pays for a call
again only when its inputs changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from typing import Any, Callable, Optional

import deps
from ai_helpers import load_schema
from engagement_series import SignalSeries
from insight_prompts import (
    build_engagement_explain_prompt,
    build_engagement_recommend_prompt,
)
from report_builder import (
    apply_explanations,
    apply_recommendations,
    build_report_core,
    explain_requests,
    recommendation_inputs,
)
from signal_files import SignalFileError, read_signal_csv
from signal_parser import parse_signal_csv
from signal_templates import generate_template_series, list_templates

from insight_jobs.staged_processor import JobContext, Stage, StagedJobProcessor

logger = logging.getLogger(__name__)

WAITING_STAGE = "waiting"
EXPLAIN_SCHEMA = "engagement-explain-schema"
RECOMMEND_SCHEMA = "engagement-recommend-schema"
MAX_SIGNAL_NOTES = 3
_WAITING_DETAIL = "Waiting for scene analysis"
_ANALYSIS_MISSING = (
    "The scene analysis this report was built on no longer exists. "
    "Start a new engagement analysis."
)
_ANALYSIS_FAILED = (
    "The scene analysis of this video failed, so the report could not be built. "
    "Retry the scene analysis, then retry this report."
)
_ANALYSIS_ARCHIVED = (
    "The scene analysis of this video was archived before it finished, so it "
    "will not complete. Start a new engagement analysis."
)
_TIMELINE_UNREADABLE = "The scene analysis timeline could not be read."
_CSV_MISSING = "This report has no signal CSV. Start a new engagement analysis."
_CSV_UNREADABLE = (
    "The signal CSV could not be downloaded. It may have been deleted from Files."
)
_EXPLAIN_NOTE = "Explanations could not be generated"
_RECOMMEND_NOTE = "Recommendations could not be generated"
_NO_EVIDENCE_NOTE = "Too little timeline detail for recommendations"
_RECOMMENDATION_LISTS = ("do_more", "do_less", "segment_fixes")
_INPUT_LISTS = ("top_influence", "bottom_influence", "high_segments", "low_segments")
_TEMPLATE_LABELS: dict[str, str] = {t["id"]: t["label"] for t in list_templates()}


def dependency_error(analysis: Optional[Any]) -> Optional[str]:
    """Why a job can never run on this scene analysis; None while it still can.

    A completed analysis is usable even when archived. An archived analysis
    that has not completed never will: the scene processor skips archived jobs.
    """
    if analysis is None:
        return _ANALYSIS_MISSING
    if analysis.status == "completed":
        return None
    if analysis.status == "failed":
        return _ANALYSIS_FAILED
    return _ANALYSIS_ARCHIVED if analysis.archived else None


def restore_series(saved: Optional[dict], stamp: dict) -> Optional[SignalSeries]:
    """The series in a `signal` checkpoint, or None if it is for other inputs."""
    if not saved or saved.get("stamp") != stamp:
        return None
    try:
        payload = saved["series"]
        metrics = {
            str(label): [(float(when), float(value)) for when, value in points]
            for label, points in payload["metrics"].items()
        }
        series = SignalSeries(
            metrics=metrics,
            primary_metric=str(payload["primary_metric"]),
            interval_sec=float(payload["interval_sec"]),
            duration_sec=float(payload["duration_sec"]),
            time_column=payload.get("time_column"),
            warnings=[str(note) for note in payload.get("warnings") or []],
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    return series if series.points else None


def _has_explanations(data: dict) -> bool:
    items = data.get("explanations")
    return isinstance(items, list) and any(isinstance(item, dict) for item in items)


def _has_recommendations(data: dict) -> bool:
    lists = (data.get(name) for name in _RECOMMENDATION_LISTS)
    return bool(data.get("headline")) or any(isinstance(v, list) and v for v in lists)


def _prompt_digest(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


class EngagementProcessor(StagedJobProcessor):
    """Processes pending engagement jobs whose scene analysis is completed."""

    record_prefix = "engagement"
    stages = (
        Stage("signal", 15),
        Stage("stats", 15),
        Stage("explain", 40),
        Stage("recommend", 30),
    )

    @property
    def name(self) -> str:
        return "engagement"

    @property
    def firestore_update_method(self) -> str:
        return "update_engagement"

    # ── Dependency gate ──────────────────────────────────────────────

    def get_pending_records(self) -> list:
        """Pending jobs that can run now.

        A job whose scene analysis is failed, missing, or archived before it
        completed is marked failed. One whose analysis is still running stays
        pending with `stage="waiting"`. All analyses are read in one list
        call per poll, and only when a job is actually pending.
        """
        records = deps.firestore_svc.get_engagements(include_archived=False)
        pending = [r for r in records if r.status == "pending"]
        if not pending:
            return []
        analyses = {
            a.id: a
            for a in deps.firestore_svc.get_scene_analyses(include_archived=True)
        }
        return [r for r in pending if self._gate(r, analyses.get(r.scene_analysis_id))]

    def _gate(self, record: Any, analysis: Optional[Any]) -> bool:
        """True if `record` can run now; otherwise fail it or mark it waiting."""
        error = dependency_error(analysis)
        if error:
            logger.warning(
                f"[{self.name}:{record.id}] Cannot run: {error}",
                extra=self._log_ctx(
                    "_gate", f"dependency_failed:{record.scene_analysis_id}", error
                ),
            )
            self.update_status(
                record.id, "failed", 0, error_message=error, stage="", stage_detail=""
            )
            return False
        if analysis is not None and analysis.status == "completed":
            return True
        if record.stage != WAITING_STAGE:
            # Written once: a waiting job is polled every few seconds.
            self.update_status(
                record.id,
                "pending",
                0,
                stage=WAITING_STAGE,
                stage_detail=_WAITING_DETAIL,
            )
        return False

    # ── Inputs ───────────────────────────────────────────────────────

    def _timeline(self, ctx: JobContext) -> dict:
        """The linked analysis's `timeline.json`, downloaded on first use."""
        if "timeline" not in ctx.state:
            ctx.state["timeline"] = self._read_timeline(ctx.record)
        return ctx.state["timeline"]

    def _read_timeline(self, record: Any) -> dict:
        analysis = deps.firestore_svc.get_scene_analysis(record.scene_analysis_id)
        error = dependency_error(analysis)
        if error or not analysis.timeline_gcs_uri:
            raise RuntimeError(error or _TIMELINE_UNREADABLE)
        try:
            timeline = json.loads(
                deps.storage_svc.download_bytes(analysis.timeline_gcs_uri)
            )
        except Exception as exc:
            logger.error(
                f"[{self.name}:{record.id}] Timeline unreadable: {exc}",
                extra=self._log_ctx("_read_timeline", "timeline_unreadable", str(exc)),
            )
            raise RuntimeError(_TIMELINE_UNREADABLE) from exc
        if not isinstance(timeline, dict):
            raise RuntimeError(_TIMELINE_UNREADABLE)
        return timeline

    def _read_csv(self, record: Any) -> bytes:
        """The record's BARC CSV; size and storage problems become readable errors."""
        uri = record.signal.csv_gcs_uri
        if not uri:
            raise RuntimeError(_CSV_MISSING)
        try:
            return read_signal_csv(uri)
        except SignalFileError:
            raise
        except Exception as exc:
            logger.error(
                f"[{self.name}:{record.id}] Signal CSV unreadable: {exc}",
                extra=self._log_ctx("_read_csv", "csv_unreadable", str(exc)),
            )
            raise RuntimeError(_CSV_UNREADABLE) from exc

    # ── Stage 1: signal ──────────────────────────────────────────────

    def stage_signal(self, ctx: JobContext) -> None:
        duration = float(self._timeline(ctx).get("duration_sec") or 0.0)
        stamp = {"signal": ctx.record.signal.model_dump(), "duration_sec": duration}
        series = restore_series(self.load_checkpoint(ctx.record_id, "signal"), stamp)
        if series is None:
            series = self._build_series(ctx.record, duration)
            payload = {"stamp": stamp, "series": asdict(series)}
            self.save_checkpoint(ctx.record_id, "signal", payload)
        ctx.state["series"] = series
        self.report(ctx, 1.0, f"{len(series.points)} samples")

    def _build_series(self, record: Any, duration_sec: float) -> SignalSeries:
        """Generate the template curve or parse the CSV. `ValueError`s are user-readable."""
        spec = record.signal
        if spec.kind == "template":
            return generate_template_series(
                spec.template_id or "", duration_sec, seed=record.id
            )
        return parse_signal_csv(
            self._read_csv(record),
            time_column=spec.time_column,
            metric=spec.metric,
            offset_sec=spec.offset_sec,
        )

    # ── Stage 2: stats ───────────────────────────────────────────────

    def stage_stats(self, ctx: JobContext) -> None:
        series: SignalSeries = ctx.state["series"]
        spec = ctx.record.signal
        meta = {
            "kind": spec.kind,
            "template_id": spec.template_id,
            "label": _TEMPLATE_LABELS.get(spec.template_id or "") or spec.csv_filename,
            "offset_sec": spec.offset_sec,
        }
        report = build_report_core(self._timeline(ctx), series, meta)
        ctx.state["report"] = report
        ctx.notes.extend(series.warnings[:MAX_SIGNAL_NOTES])
        found = f"{len(report['extrema'])} moments found"
        self.report(ctx, 1.0, found, duration_sec=report["duration_sec"])

    # ── Stages 3 and 4: prose from the model ─────────────────────────

    def _ask(
        self,
        ctx: JobContext,
        name: str,
        prompt: str,
        schema: str,
        usable: Callable[[dict], bool],
    ) -> Optional[dict]:
        """Checkpointed structured model call; None when no usable answer came back.

        Never raises for a model failure. Usage is counted whether the answer
        was usable or not, and for a reused checkpoint too, so the record
        shows what the report cost in total.
        """
        digest = _prompt_digest(prompt)
        saved = self.load_checkpoint(ctx.record_id, name) or {}
        if saved.get("prompt_sha256") == digest and isinstance(saved.get("data"), dict):
            self.add_usage(ctx, saved.get("usage"))
            return saved["data"]
        record = ctx.record
        try:
            response = self._run_async(
                deps.ai_svc.generate_insight_json(
                    prompt,
                    load_schema(schema),
                    model_id=record.model_id,
                    region=record.region,
                )
            )
        except Exception as exc:
            self._warn_model(ctx, name, f"call_failed: {exc}")
            return None
        self.add_usage(ctx, response.usage)
        reason = getattr(response, "finish_reason", "")
        data = response.data if isinstance(response.data, dict) else {}
        if reason == "MAX_TOKENS" or not usable(data):
            self._warn_model(ctx, name, f"unusable_output finish_reason={reason}")
            return None
        answer = {
            "prompt_sha256": digest,
            "data": data,
            "usage": response.usage.model_dump(),
        }
        self.save_checkpoint(ctx.record_id, name, answer)
        return data

    def _warn_model(self, ctx: JobContext, name: str, why: str) -> None:
        logger.warning(
            f"[{self.name}:{ctx.record_id}] No usable '{name}' answer: {why}",
            extra=self._log_ctx("_ask", f"soft_failure:{name}", why),
        )

    def stage_explain(self, ctx: JobContext) -> None:
        report, timeline = ctx.state["report"], self._timeline(ctx)
        moments = explain_requests(report, timeline)
        if not moments:
            return
        self.report(ctx, 0.1, f"Explaining {len(moments)} moments")
        overview = {
            "content_title": timeline.get("content_title") or "",
            "summary": timeline.get("summary") or "",
            "duration_sec": report["duration_sec"],
        }
        prompt = build_engagement_explain_prompt(report["signal"], moments, overview)
        data = self._ask(ctx, "explain", prompt, EXPLAIN_SCHEMA, _has_explanations)
        if data is not None:
            report = apply_explanations(report, data["explanations"])
            ctx.state["report"] = report
        if not any(e["title"] or e["explanation"] for e in report["extrema"]):
            ctx.notes.append(_EXPLAIN_NOTE)

    def stage_recommend(self, ctx: JobContext) -> None:
        report, timeline = ctx.state["report"], self._timeline(ctx)
        inputs = recommendation_inputs(report, timeline)
        if any(inputs.get(name) for name in _INPUT_LISTS):
            self.report(ctx, 0.1, "Writing recommendations")
            prompt = build_engagement_recommend_prompt(inputs)
            data = self._ask(
                ctx, "recommend", prompt, RECOMMEND_SCHEMA, _has_recommendations
            )
            if data is None:
                ctx.notes.append(_RECOMMEND_NOTE)
            else:
                report = apply_recommendations(report, data, timeline)
        else:
            ctx.notes.append(_NO_EVIDENCE_NOTE)
        ctx.state["report"] = report
        ctx.state["report_uri"] = self.save_json(ctx.record_id, "report.json", report)

    # ── Completion ───────────────────────────────────────────────────

    def completion_updates(self, ctx: JobContext) -> dict[str, Any]:
        report = ctx.state["report"]
        return {
            "report_gcs_uri": ctx.state["report_uri"],
            "duration_sec": report["duration_sec"],
            "headline": report["recommendations"]["headline"],
            "kpis": report["kpis"],
        }

"""Generic staged job processor: ordered stages, progress and GCS checkpoints.

`StagedJobProcessor` is the base for worker jobs that run as a fixed sequence
of named stages and must be cheap to retry. It owns the job loop; a subclass
describes the stages and does the work.

Extension points
----------------
Declare on the subclass:

* `name`, `firestore_update_method`, `get_pending_records()`: as for any
  `JobProcessor`.
* `record_prefix`: the GCS folder for this record type. Everything the job
  stores lives under `{record_prefix}/{record_id}/`.
* `stages`: ordered `Stage(name, weight, status)` tuples. `weight` is the
  stage's share of the progress bar; `status` is the record status written
  while the stage runs.
* one method per stage, `stage_<name>(self, ctx)`. Override `run_stage` to
  dispatch differently.
* `completion_updates(ctx)`: extra record fields written with
  `status="completed"` (summaries, output URIs).

Helpers available to stage methods:

* `report(ctx, fraction, detail, **fields)`: write `status`, `stage`,
  `stage_detail` and `progress_pct` (plus any extra record fields).
  `fraction` is progress within the current stage, 0..1.
* `save_checkpoint` / `load_checkpoint(record_id, name)`: JSON checkpoints at
  `{record_prefix}/{record_id}/{name}.json`. A missing or unreadable
  checkpoint loads as `None`, so the stage simply redoes the work.
* `save_json(record_id, filename, payload)`: store a JSON output and return
  its `gs://` URI. `record_path` / `record_uri` build paths under the record.
* `add_usage(ctx, usage)`: add a call's token usage to the job total, which is
  written to the record's `usage` field on completion.
* `ctx.state`: values handed from one stage to the next. `ctx.notes`:
  non-fatal problems; they are joined into `stage_detail` on completion.
* `ctx.tmp`: a `TempFileManager`; its files are removed when the job ends,
  whether it succeeded or failed.

A stage fails the job by raising. The unified worker then marks the record
`failed` with the exception text; the record keeps the `stage` it failed in.
Checkpoints stay in GCS, so the retried job skips work that already finished.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import deps
from models import UsageMetrics

from base_processor import JobProcessor, TempFileManager

logger = logging.getLogger(__name__)

_JSON_CONTENT_TYPE = "application/json"
# 100 is written only with status="completed".
_MAX_RUNNING_PCT = 99


@dataclass(frozen=True)
class Stage:
    """One named step of a staged job."""

    name: str
    weight: float = 1.0
    status: str = "processing"


@dataclass
class JobContext:
    """Per-run state shared by the stages of one job."""

    record: Any
    tmp: TempFileManager
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    state: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    stage: Optional[Stage] = None

    @property
    def record_id(self) -> str:
        return self.record.id


def sum_usage(
    total: UsageMetrics, extra: Union[UsageMetrics, dict, None]
) -> UsageMetrics:
    """Return `total` plus the text-token usage of one more model call."""
    if not extra:
        return total
    added = extra if isinstance(extra, UsageMetrics) else UsageMetrics(**extra)
    return total.model_copy(
        update={
            "input_tokens": total.input_tokens + added.input_tokens,
            "output_tokens": total.output_tokens + added.output_tokens,
            "cost_usd": total.cost_usd + added.cost_usd,
            "model_name": added.model_name or total.model_name,
        }
    )


class StagedJobProcessor(JobProcessor):
    """Runs a job as ordered stages with progress updates and GCS checkpoints.

    See the module docstring for the extension points.
    """

    record_prefix: str = ""
    stages: tuple[Stage, ...] = ()

    # ── Job loop ─────────────────────────────────────────────────────

    def process(self, record: Any) -> None:
        """Run every stage in order, then mark the record completed."""
        ctx = JobContext(record=record, tmp=TempFileManager())
        try:
            for stage in self.stages:
                ctx.stage = stage
                self.report(ctx)
                self.run_stage(ctx, stage)
            self._complete(ctx)
        finally:
            ctx.tmp.cleanup()

    def run_stage(self, ctx: JobContext, stage: Stage) -> None:
        """Run one stage. Default: call `self.stage_<name>(ctx)`."""
        getattr(self, f"stage_{stage.name}")(ctx)

    def completion_updates(self, ctx: JobContext) -> dict[str, Any]:
        """Extra record fields to write when the job completes."""
        return {}

    def _complete(self, ctx: JobContext) -> None:
        updates = {
            "stage": "",
            "stage_detail": "; ".join(ctx.notes),
            "usage": ctx.usage.model_dump(),
            **self.completion_updates(ctx),
        }
        self.update_status(ctx.record_id, "completed", 100, **updates)
        logger.info(
            f"[{self.name}:{ctx.record_id}] Completed",
            extra=self._log_ctx("_complete", f"completed:{ctx.record_id}", "job_done"),
        )

    def _log_ctx(self, where: str, what: str, why: str) -> dict[str, str]:
        return {
            "who": self.name,
            "where": where,
            "what": what,
            "why": why,
            "how": "staged_job",
        }

    # ── Progress ─────────────────────────────────────────────────────

    def progress_pct(self, stage: Stage, fraction: float = 0.0) -> int:
        """Overall percent (0..99) for `fraction` (0..1) of the way through `stage`."""
        total = sum(s.weight for s in self.stages) or 1.0
        done = 0.0
        for candidate in self.stages:
            if candidate.name == stage.name:
                break
            done += candidate.weight
        within = stage.weight * min(1.0, max(0.0, fraction))
        return min(_MAX_RUNNING_PCT, int(100 * (done + within) / total))

    def report(
        self, ctx: JobContext, fraction: float = 0.0, detail: str = "", **fields: Any
    ) -> None:
        """Persist progress for the current stage, plus any extra record fields."""
        stage = ctx.stage
        if stage is None:
            raise RuntimeError("report() called outside a stage")
        self.update_status(
            ctx.record_id,
            stage.status,
            self.progress_pct(stage, fraction),
            stage=stage.name,
            stage_detail=detail,
            **fields,
        )

    def add_usage(
        self, ctx: JobContext, usage: Union[UsageMetrics, dict, None]
    ) -> None:
        """Add one model call's usage to the job total."""
        ctx.usage = sum_usage(ctx.usage, usage)

    # ── GCS storage under the record prefix ──────────────────────────

    def record_path(self, record_id: str, name: str) -> str:
        """Bucket-relative path of `name` under this record's folder."""
        return f"{self.record_prefix}/{record_id}/{name}"

    def record_uri(self, record_id: str, name: str) -> str:
        """`gs://` URI of `name` under this record's folder."""
        bucket = deps.storage_svc.bucket_name
        return f"gs://{bucket}/{self.record_path(record_id, name)}"

    def save_json(self, record_id: str, filename: str, payload: dict) -> str:
        """Write `payload` as JSON under the record folder; return its `gs://` URI."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return deps.storage_svc.upload_bytes(
            data, self.record_path(record_id, filename), _JSON_CONTENT_TYPE
        )

    def load_json(self, record_id: str, filename: str) -> Optional[dict]:
        """Read a JSON object from the record folder; None if absent or unreadable."""
        uri = self.record_uri(record_id, filename)
        try:
            if not deps.storage_svc.blob_exists(uri):
                return None
            payload = json.loads(deps.storage_svc.download_bytes(uri))
        except Exception as exc:
            logger.warning(
                f"[{self.name}:{record_id}] Ignoring unreadable {filename}: {exc}",
                extra=self._log_ctx("load_json", f"unreadable:{filename}", str(exc)),
            )
            return None
        return payload if isinstance(payload, dict) else None

    def save_checkpoint(self, record_id: str, name: str, payload: dict) -> str:
        """Store a checkpoint at `{record_prefix}/{record_id}/{name}.json`."""
        return self.save_json(record_id, f"{name}.json", payload)

    def load_checkpoint(self, record_id: str, name: str) -> Optional[dict]:
        """Load a checkpoint saved by `save_checkpoint`; None if there is none."""
        return self.load_json(record_id, f"{name}.json")

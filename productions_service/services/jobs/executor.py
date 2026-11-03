"""Bounded background executor for stage runs: single-flight claim, run, terminal outcome.

`submit_job` claims the project (409 if a run is live), registers the run with the
heartbeat tracker and hands the work to a bounded thread pool, returning `202 RunAccepted`
at once. The work function is the existing synchronous service call; its outcome maps to:
completed | paused (gate block / shots awaiting review — graceful stop) | failed.

Cloud Run note: deployed with `--no-cpu-throttling --min-instances 1 --timeout 3600`
(scripts/deploy.sh), so pool threads keep running after the HTTP response. A run whose
instance dies stops heartbeating and is reported `interrupted` (see `liveness`).
"""

from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from storygraph import progress
from storygraph.errors import GateBlocked, ShotsNotApproved, describe_exception
from storygraph.repo.stage_jobs import RunConflict, StageJobRepo
from storygraph.schema import Role
from storygraph.schemas.stage_job import RunKind, RunStatus, StageJob
from storygraph.store.base import GraphStore

from .contract import RunAccepted, RunView
from .liveness import is_live, utc_now
from .tracker import JobTracker, RunSink

logger = logging.getLogger(__name__)
JobResult = dict[str, Any] | None
JobFn = Callable[[], JobResult]
_GRACEFUL = (GateBlocked, ShotsNotApproved)

_pool = ThreadPoolExecutor(
    max_workers=max(1, int(os.getenv("STAGE_JOB_WORKERS", "4"))),
    thread_name_prefix="stage-job",
)
_tracker = JobTracker()
_claim_lock = (
    threading.Lock()
)  # same-instance double clicks; the store tx covers instances


class RunPaused(Exception):
    """Raised by a job function for a graceful stop (e.g. pipeline waits at a gate)."""


@dataclass(frozen=True)
class JobSpec:
    kind: RunKind
    label: str
    fn: JobFn
    stages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Outcome:
    status: RunStatus
    error: str | None = None
    result: JobResult = None


def _log(what: str, why: str, project_id: str, job: StageJob, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.jobs.executor",
            "what": what,
            "when": utc_now().isoformat(),
            "why": why,
            "how": f"{job.kind} run in bounded background pool",
            "project_id": project_id,
            "run_id": job.id,
            "stage": job.stage,
            **extra,
        },
    )


def _crash_extra(project_id: str) -> dict[str, Any]:
    return {
        "who": "productions_service",
        "where": "services.jobs.executor._outcome",
        "what": "stage_job_crashed",
        "when": utc_now().isoformat(),
        "why": "unexpected exception escaped the run",
        "how": "recorded as failed run",
        "project_id": project_id,
    }


def _new_job(spec: JobSpec) -> StageJob:
    now = utc_now()
    return StageJob(
        id=f"run_{now:%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}",
        created_by=Role.HUMAN,
        kind=spec.kind,
        label=spec.label,
        stage=spec.stages[0] if spec.stages else None,
        stages=list(spec.stages),
        started_at=now,
        heartbeat_at=now,
    )


def _claim(jobs: StageJobRepo, job: StageJob) -> None:
    try:
        with _claim_lock:
            jobs.claim(job, lambda j: is_live(j, utc_now()))
    except RunConflict as rc:
        detail = (
            "A run is already in progress for this production: "
            f"{rc.active.id} ({rc.active.label})"
        )
        raise HTTPException(status_code=409, detail=detail) from rc


def submit_job(store: GraphStore, spec: JobSpec) -> dict[str, Any]:
    """Claim the project, queue `spec.fn` in the background, answer `RunAccepted`."""
    jobs, job = StageJobRepo(store), _new_job(spec)
    _claim(jobs, job)
    sink = _tracker.track(job, jobs)
    _spawn(store.project_id, job, sink, spec.fn)
    _log("run accepted", spec.label, store.project_id, job, stages=list(spec.stages))
    return RunAccepted(stage_run_id=job.id, run=RunView.of(job, "queued")).model_dump(
        mode="json"
    )


def _spawn(project_id: str, job: StageJob, sink: RunSink, fn: JobFn) -> Future[None]:
    return _pool.submit(_execute, project_id, job, sink, fn)


def _graceful_cause(exc: BaseException) -> bool:
    """True for a gate block / shots-awaiting-review, also when wrapped in HTTPException."""
    return isinstance(exc, _GRACEFUL) or isinstance(exc.__context__, _GRACEFUL)


def _outcome(project_id: str, sink: RunSink, fn: JobFn) -> Outcome:
    with progress.bound(project_id, sink):
        try:
            return Outcome("completed", result=fn())
        except RunPaused as rp:
            return Outcome("paused", error=str(rp))
        except HTTPException as he:
            status: RunStatus = "paused" if _graceful_cause(he) else "failed"
            return Outcome(status, error=str(he.detail))
        except Exception as exc:  # noqa: BLE001 - run boundary: record, never crash pool
            status = "paused" if _graceful_cause(exc) else "failed"
            if status == "failed":
                logger.exception("stage job crashed", extra=_crash_extra(project_id))
            return Outcome(status, error=describe_exception(exc)[:2000])


def _execute(project_id: str, job: StageJob, sink: RunSink, fn: JobFn) -> None:
    _tracker.mutate(job.id, lambda j: j.model_copy(update={"run_status": "running"}))
    _log("run started", job.label, project_id, job)
    out = _outcome(project_id, sink, fn)
    upd: dict[str, Any] = {
        "run_status": out.status,
        "error": out.error,
        "result": out.result,
    }
    try:
        final = _tracker.finish(job.id, lambda j: j.model_copy(update=upd))
    except Exception as exc:  # noqa: BLE001 - heartbeat stops -> shows interrupted
        _log("run final write failed", describe_exception(exc), project_id, job)
        return
    _log(f"run {out.status}", out.error or job.label, project_id, final or job)

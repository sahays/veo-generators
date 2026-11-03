"""Typed HTTP contract for async stage runs and the lightweight status endpoint.

Mirrored 1:1 by `frontend/src/types/runs.ts`.

* `POST` run endpoints answer `202 RunAccepted` immediately; the work continues in the
  bounded background executor (`services.jobs.executor`). A second run for the same
  project while one is live answers `409` (detail names the active run id).
* `GET /api/v1/productions/{id}/status` answers `ProductionStatusResponse` from three small
  Firestore document reads (no snapshot, no URL signing).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel
from storygraph.schemas.stage_job import RunKind, RunProgress, RunStatus, StageJob


class RunView(BaseModel):
    run_id: str
    kind: RunKind
    label: str
    stage: str | None = None
    stages: list[str] = []
    status: RunStatus
    progress: RunProgress | None = None
    started_at: str
    heartbeat_at: str
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None

    @classmethod
    def of(cls, job: StageJob, status: RunStatus) -> RunView:
        return cls(
            run_id=job.id,
            kind=job.kind,
            label=job.label,
            stage=job.stage,
            stages=list(job.stages),
            status=status,
            progress=job.progress,
            started_at=job.started_at.isoformat(),
            heartbeat_at=job.heartbeat_at.isoformat(),
            finished_at=job.finished_at.isoformat() if job.finished_at else None,
            error=job.error,
            result=job.result,
        )


class RunAccepted(BaseModel):
    accepted: Literal[True] = True
    stage_run_id: str
    run: RunView


class ProductionStatusResponse(BaseModel):
    project_id: str
    pipeline_status: str
    current_stage: str | None = None
    active_run: RunView | None = None  # queued / running only
    last_run: RunView | None = None  # most recent finished or interrupted run
    last_error: str | None = None
    server_time: str

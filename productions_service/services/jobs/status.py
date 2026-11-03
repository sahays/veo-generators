"""`GET /api/v1/productions/{id}/status`: pipeline status + active/last run, cheap.

Three small document reads (`meta/project`, `meta/active_job`, `stage_jobs/<id>`) on a
store built without blobs or the legacy auto-seed reads: no snapshot, no URL signing.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from storygraph.repo.stage_jobs import StageJobRepo
from storygraph.schemas.stage_job import LIVE_STATUSES, StageJob

from ..runtime import get_graph_store
from .contract import ProductionStatusResponse, RunView
from .liveness import effective_status, interrupted_message, utc_now

_PROJECT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _views(job: StageJob | None) -> tuple[RunView | None, RunView | None]:
    """(active_run, last_run) for the project's most recent run."""
    if job is None:
        return None, None
    status = effective_status(job, utc_now())
    if status in LIVE_STATUSES:
        return RunView.of(job, status), None
    view = RunView.of(job, status)
    if status == "interrupted" and not view.error:
        view = view.model_copy(update={"error": interrupted_message(job)})
    return None, view


def get_production_status(project_id: str) -> dict[str, Any]:
    if not _PROJECT_ID.fullmatch(project_id):
        raise HTTPException(status_code=400, detail="invalid project id")
    store = get_graph_store(project_id)
    meta = store.get("meta", "project")
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")
    active, last = _views(StageJobRepo(store).latest())
    run_error = last.error if last and last.status != "completed" else None
    return ProductionStatusResponse(
        project_id=project_id,
        pipeline_status=str(meta.get("status") or "draft"),
        current_stage=meta.get("current_stage"),
        active_run=active,
        last_run=last,
        last_error=run_error or meta.get("error_message"),
        server_time=utc_now().isoformat(),
    ).model_dump(mode="json")

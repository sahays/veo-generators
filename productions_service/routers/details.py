"""HTTP routes for lazily loaded studio details (kept out of the first-paint snapshot)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from services.details import (
    AUDIT_PAGE_DEFAULT,
    AUDIT_PAGE_MAX,
    audit_log_page,
    scene_detail,
    shot_run_history,
)

router = APIRouter()


@router.get("/api/v1/productions/{project_id}/shots/{shot_id}/runs")
async def get_shot_runs(project_id: str, shot_id: str) -> dict[str, Any]:
    return await run_in_threadpool(shot_run_history, project_id, shot_id)


@router.get("/api/v1/productions/{project_id}/graph/audit-log")
async def get_audit_log(
    project_id: str,
    limit: int = Query(AUDIT_PAGE_DEFAULT, ge=1, le=AUDIT_PAGE_MAX),
    cursor: str | None = Query(None, max_length=2048),
) -> dict[str, Any]:
    return await run_in_threadpool(audit_log_page, project_id, limit, cursor)


@router.get("/api/v1/productions/{project_id}/graph/scenes/{scene_id}")
async def get_scene_detail(project_id: str, scene_id: str) -> dict[str, Any]:
    return await run_in_threadpool(scene_detail, project_id, scene_id)

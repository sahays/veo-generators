"""HTTP routes for the Blender previz tab (contract: `services/previz_contract.py`)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path
from fastapi.concurrency import run_in_threadpool

from services.previz_contract import ID_PATTERN, PrevizRunPayload, PromotePrevizPayload
from services.previz_service import (
    get_previz_board,
    promote_shot_previz,
    start_previz_run,
)

router = APIRouter()
ProjectId = Path(..., pattern=ID_PATTERN)
ShotId = Path(..., pattern=ID_PATTERN)


@router.get("/api/v1/productions/{project_id}/previz")
async def get_production_previz(project_id: str = ProjectId) -> dict[str, Any]:
    return await run_in_threadpool(get_previz_board, project_id)


@router.post("/api/v1/productions/{project_id}/previz/run")
async def run_production_previz(
    body: PrevizRunPayload, project_id: str = ProjectId
) -> dict[str, Any]:
    return await run_in_threadpool(start_previz_run, project_id, body)


@router.post("/api/v1/productions/{project_id}/previz/shots/{shot_id}/promote")
async def promote_production_previz(
    body: PromotePrevizPayload, project_id: str = ProjectId, shot_id: str = ShotId
) -> dict[str, Any]:
    return await run_in_threadpool(promote_shot_previz, project_id, shot_id, body)

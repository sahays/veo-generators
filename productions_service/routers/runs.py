"""Async run endpoints (`202 RunAccepted`) and the lightweight `GET .../status`.

Every long-running production action returns at once; the work continues in the bounded
background executor (`services.jobs`). Clients poll `GET /api/v1/productions/{id}/status`.
Included by `routers.productions` so the app wiring (`main.py`) is unchanged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from fastapi.concurrency import run_in_threadpool
from services.assembly_service import AssembleMode
from services.jobs import entrypoints as runs
from services.jobs.status import get_production_status
from services.keyframes_contract import RegenerateKeyframePayload
from services.productions_service import (
    GateDecisionPayload,
    RunPipelinePayload,
    approve_project_gate,
    run_project_stage,
)
from services.repair_service import RepairShotsPayload

router = APIRouter()
BASE = "/api/v1/productions/{project_id}"
ACCEPTED = 202


@router.get(f"{BASE}/status")
async def get_status(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(get_production_status, project_id)


@router.post(f"{BASE}/run", status_code=ACCEPTED)
async def run_pipeline(
    project_id: str, body: RunPipelinePayload | None = None
) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_pipeline_run, project_id, body)


@router.post(f"{BASE}/stages/{{stage_id}}/run", status_code=ACCEPTED)
async def run_stage(
    project_id: str,
    stage_id: str,
    response: Response,
    force: bool = True,
    quality: str | None = None,
    cascade: bool = False,
) -> dict[str, Any]:
    if not runs.is_pipeline_stage(stage_id):  # e.g. S8_PREVIZ: its own background run
        response.status_code = 200
        return await run_in_threadpool(
            run_project_stage, project_id, stage_id, force, quality
        )
    return await run_in_threadpool(
        runs.start_stage_run, project_id, stage_id, force, quality, cascade
    )


@router.post(f"{BASE}/gates/{{gate_id}}/approve", status_code=ACCEPTED)
async def approve_gate(
    project_id: str,
    gate_id: str,
    response: Response,
    body: GateDecisionPayload | None = None,
    advance: bool = True,
) -> dict[str, Any]:
    if not advance:  # approval only: quick, answers the refreshed snapshot
        response.status_code = 200
        return await run_in_threadpool(
            approve_project_gate, project_id, gate_id, body, False
        )
    return await run_in_threadpool(runs.start_gate_advance, project_id, gate_id, body)


@router.post(f"{BASE}/assemble", status_code=ACCEPTED)
async def assemble(
    project_id: str, mode: AssembleMode = "approved_only"
) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_assembly, project_id, mode)


@router.post(f"{BASE}/analyze", status_code=ACCEPTED)
async def analyze_compat(
    project_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_compat_run, project_id, body, "analyze")


@router.post(f"{BASE}/render", status_code=ACCEPTED)
async def render_compat(
    project_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_compat_run, project_id, body, "render")


@router.post(f"{BASE}/appearances/{{appearance_id}}/regenerate", status_code=ACCEPTED)
async def regenerate_appearance(project_id: str, appearance_id: str) -> dict[str, Any]:
    return await run_in_threadpool(
        runs.start_appearance_regenerate, project_id, appearance_id
    )


@router.post(f"{BASE}/shots/repair", status_code=ACCEPTED)
async def repair_shots(
    project_id: str, body: RepairShotsPayload | None = None
) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_repair, project_id, body)


@router.post(f"{BASE}/shots/{{shot_id}}/regenerate", status_code=ACCEPTED)
async def regenerate_shot(project_id: str, shot_id: str) -> dict[str, Any]:
    return await run_in_threadpool(runs.start_shot_regenerate, project_id, shot_id)


@router.post(
    f"{BASE}/shots/{{shot_id}}/keyframes/{{t}}/regenerate", status_code=ACCEPTED
)
async def regenerate_keyframes(
    project_id: str,
    shot_id: str,
    t: float,
    body: RegenerateKeyframePayload | None = None,
) -> dict[str, Any]:
    return await run_in_threadpool(
        runs.start_keyframe_regenerate, project_id, shot_id, t, body
    )

"""HTTP route handlers for `/api/v1/productions/*`, delegating to `services.productions_service`.

Long-running actions (runs, stages, gates-with-advance, assemble, repair, regenerate) live
in `routers.runs` (async: 202 + background job + `GET .../status`), included below.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from services.assembly_service import get_assembly_readiness
from services.keyframes_service import get_keyframe_board, get_shot_keyframes
from services.productions_service import (
    CreateProductionPayload,
    GateDecisionPayload,
    approve_project_appearance,
    compile_project_shot_preview,
    create_production_project,
    get_production_project,
    list_production_projects,
    reject_project_gate,
    update_production_project,
)
from services.prompt_versions_service import (
    HumanPromptPayload,
    activate_shot_prompt,
    create_human_shot_prompt,
    list_shot_prompts,
)
from services.repair_service import ClipEdit, edit_project_shot_clip

from .runs import router as runs_router

router = APIRouter()
router.include_router(runs_router)


@router.post("/api/v1/productions")
async def create_production(
    body: CreateProductionPayload, request: Request
) -> dict[str, Any]:
    invite_code = request.headers.get("X-Invite-Code", "")
    return await run_in_threadpool(create_production_project, body, invite_code)


@router.get("/api/v1/productions")
async def list_productions(archived: bool = False) -> list[dict[str, Any]]:
    return await run_in_threadpool(list_production_projects, archived)


@router.get("/api/v1/productions/{project_id}")
@router.get("/api/v1/productions/{project_id}/graph")
async def get_production(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(get_production_project, project_id)


@router.patch("/api/v1/productions/{project_id}")
async def update_production(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return await run_in_threadpool(update_production_project, project_id, updates)


@router.delete("/api/v1/productions/{project_id}")
@router.post("/api/v1/productions/{project_id}/archive")
async def archive_production(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(
        update_production_project, project_id, {"archived": True}
    )


@router.post("/api/v1/productions/{project_id}/unarchive")
async def unarchive_production(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(
        update_production_project, project_id, {"archived": False}
    )


@router.get("/api/v1/productions/{project_id}/assembly-readiness")
async def get_production_assembly_readiness(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(get_assembly_readiness, project_id)


@router.post("/api/v1/productions/{project_id}/gates/{gate_id}/reject")
async def reject_production_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
) -> dict[str, Any]:
    return await run_in_threadpool(reject_project_gate, project_id, gate_id, body)


@router.post("/api/v1/productions/{project_id}/appearances/{appearance_id}/approve")
async def approve_single_appearance(
    project_id: str, appearance_id: str
) -> dict[str, Any]:
    return await run_in_threadpool(
        approve_project_appearance, project_id, appearance_id
    )


@router.post("/api/v1/productions/{project_id}/shots/{shot_id}/compile")
async def compile_single_shot_preview(project_id: str, shot_id: str) -> dict[str, Any]:
    return await run_in_threadpool(compile_project_shot_preview, project_id, shot_id)


@router.patch("/api/v1/productions/{project_id}/shots/{shot_id}/clip")
async def edit_production_shot_clip(
    project_id: str, shot_id: str, body: ClipEdit
) -> dict[str, Any]:
    return await run_in_threadpool(edit_project_shot_clip, project_id, shot_id, body)


@router.get("/api/v1/productions/{project_id}/shots/{shot_id}/prompts")
async def list_production_shot_prompts(project_id: str, shot_id: str) -> dict[str, Any]:
    return await run_in_threadpool(list_shot_prompts, project_id, shot_id)


@router.post("/api/v1/productions/{project_id}/shots/{shot_id}/prompts")
async def create_production_shot_prompt(
    project_id: str, shot_id: str, body: HumanPromptPayload
) -> dict[str, Any]:
    return await run_in_threadpool(create_human_shot_prompt, project_id, shot_id, body)


@router.post(
    "/api/v1/productions/{project_id}/shots/{shot_id}/prompts/{version_id}/activate"
)
async def activate_production_shot_prompt(
    project_id: str, shot_id: str, version_id: str
) -> dict[str, Any]:
    return await run_in_threadpool(
        activate_shot_prompt, project_id, shot_id, version_id
    )


@router.get("/api/v1/productions/{project_id}/keyframes")
async def get_production_keyframes(project_id: str) -> dict[str, Any]:
    return await run_in_threadpool(get_keyframe_board, project_id)


@router.get("/api/v1/productions/{project_id}/shots/{shot_id}/keyframes")
async def get_production_shot_keyframes(
    project_id: str, shot_id: str
) -> dict[str, Any]:
    return await run_in_threadpool(get_shot_keyframes, project_id, shot_id)

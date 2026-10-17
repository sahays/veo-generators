"""HTTP route handlers for `/api/v1/productions/*`, delegating to `services.productions_service`."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from services.productions_service import (
    CreateProductionPayload,
    GateDecisionPayload,
    RunPipelinePayload,
    analyze_project_compat,
    approve_project_appearance,
    approve_project_gate,
    compile_project_shot_preview,
    create_production_project,
    get_production_project,
    list_production_projects,
    regenerate_project_appearance,
    reject_project_gate,
    render_project_compat,
    run_pipeline_for_project,
    run_project_stage,
    update_production_project,
)

router = APIRouter()


@router.post("/api/v1/productions")
async def create_production(
    body: CreateProductionPayload, request: Request
) -> dict[str, Any]:
    invite_code = request.headers.get("X-Invite-Code", "")
    return create_production_project(body, invite_code)


@router.get("/api/v1/productions")
async def list_productions(archived: bool = False) -> list[dict[str, Any]]:
    return list_production_projects(archived=archived)


@router.get("/api/v1/productions/{project_id}")
@router.get("/api/v1/productions/{project_id}/graph")
async def get_production(project_id: str) -> dict[str, Any]:
    return get_production_project(project_id)


@router.patch("/api/v1/productions/{project_id}")
async def update_production(project_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    return update_production_project(project_id, updates)


@router.post("/api/v1/productions/{project_id}/archive")
async def archive_production(project_id: str) -> dict[str, Any]:
    return update_production_project(project_id, {"archived": True})


@router.post("/api/v1/productions/{project_id}/unarchive")
async def unarchive_production(project_id: str) -> dict[str, Any]:
    return update_production_project(project_id, {"archived": False})


@router.post("/api/v1/productions/{project_id}/run")
async def run_production_pipeline(
    project_id: str,
    body: RunPipelinePayload | None = None,
) -> dict[str, Any]:
    return run_pipeline_for_project(project_id, body=body)


@router.post("/api/v1/productions/{project_id}/analyze")
async def analyze_production_compat(
    project_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return analyze_project_compat(project_id, body=body)


@router.post("/api/v1/productions/{project_id}/render")
async def render_production_compat(
    project_id: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return render_project_compat(project_id, body=body)


@router.post("/api/v1/productions/{project_id}/stages/{stage_id}/run")
async def run_single_stage(
    project_id: str,
    stage_id: str,
    force: bool = True,
) -> dict[str, Any]:
    return run_project_stage(project_id, stage_id, force=force)


@router.post("/api/v1/productions/{project_id}/gates/{gate_id}/approve")
async def approve_production_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
    advance: bool = True,
) -> dict[str, Any]:
    return approve_project_gate(project_id, gate_id, body=body, advance=advance)


@router.post("/api/v1/productions/{project_id}/gates/{gate_id}/reject")
async def reject_production_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
) -> dict[str, Any]:
    return reject_project_gate(project_id, gate_id, body=body)


@router.post("/api/v1/productions/{project_id}/appearances/{appearance_id}/approve")
async def approve_single_appearance(
    project_id: str, appearance_id: str
) -> dict[str, Any]:
    return approve_project_appearance(project_id, appearance_id)


@router.post("/api/v1/productions/{project_id}/appearances/{appearance_id}/regenerate")
async def regenerate_single_appearance(
    project_id: str, appearance_id: str
) -> dict[str, Any]:
    return regenerate_project_appearance(project_id, appearance_id)


@router.post("/api/v1/productions/{project_id}/shots/{shot_id}/compile")
async def compile_single_shot_preview(project_id: str, shot_id: str) -> dict[str, Any]:
    return compile_project_shot_preview(project_id, shot_id)

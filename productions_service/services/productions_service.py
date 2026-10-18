"""Business logic and orchestration service for StoryGraph Productions endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from storygraph.agents.design_studio import design_single_entity
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.errors import (
    BudgetExceeded,
    GateBlocked,
    NotFound,
    PermissionDenied,
    StoryGraphError,
    ValidationFailed,
)
from storygraph.pipeline import Pipeline, Stage, approve_gate, reject_gate
from storygraph.presets import resolve_production_presets
from storygraph.schema import ProjectMeta, Status
from storygraph.views import shot_view

from .runtime import (
    MEMORY_PROJECT_INDEX,
    build_pipeline,
    get_repo,
    load_runtime_config,
    reset_storygraph_collections,
)
from .snapshot import format_graph_snapshot

_ALLOWED_PATCH_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "type",
        "base_concept",
        "story_text",
        "video_length",
        "orientation",
        "language",
        "visual_style_preset",
        "color_palette_preset",
        "director_style_preset",
        "screenplay_style_preset",
        "music_style_preset",
        "auto_approve_gates",
        "status",
        "archived",
    }
)


class CreateProductionPayload(BaseModel):
    id: str | None = None
    name: str
    type: str = "movie"
    base_concept: str
    story_text: str | None = None
    video_length: str = "60"
    orientation: str = "16:9"
    language: str = "en-IN"
    visual_style_preset: str | None = None
    color_palette_preset: str | None = None
    director_style_preset: str | None = None
    screenplay_style_preset: str | None = None
    music_style_preset: str | None = None
    auto_approve_gates: bool = False
    reference_image_url: str | None = None


class RunPipelinePayload(BaseModel):
    auto_approve_gates: bool | None = None
    story_text: str | None = None
    reset: bool = False


class GateDecisionPayload(BaseModel):
    reviewer: str = "studio_user"
    notes: str | None = None


def create_production_project(
    body: CreateProductionPayload, invite_code: str
) -> dict[str, Any]:
    """Create and seed a new StoryGraph production project."""
    project_id = body.id or f"prod_{uuid.uuid4().hex[:10]}"
    cfg = load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    ptype = body.type if body.type in ("movie", "advertizement", "social") else "movie"
    orient = body.orientation if body.orientation in ("16:9", "9:16") else "16:9"
    story = (body.story_text or body.base_concept).strip()
    bundle = resolve_production_presets(
        visual_style_id=body.visual_style_preset,
        color_palette_id=body.color_palette_preset,
        director_style_id=body.director_style_preset,
        screenplay_style_id=body.screenplay_style_preset,
        music_style_id=body.music_style_preset,
    )
    meta = ProjectMeta(
        id=project_id,
        name=body.name,
        type=ptype,  # type: ignore[arg-type]
        base_concept=body.base_concept,
        story_text=story,
        video_length=str(body.video_length),
        orientation=orient,  # type: ignore[arg-type]
        language=body.language,
        visual_style_preset=bundle.visual_style.id,
        color_palette_preset=bundle.color_palette.id,
        director_style_preset=bundle.director_style.id,
        screenplay_style_preset=bundle.screenplay_style.id,
        music_style_preset=bundle.music_style.id,
        auto_approve_gates=body.auto_approve_gates,
        status="draft",
        current_stage="S0_INGEST",
        invite_code=invite_code or None,
    )
    repo.put_project_meta(meta)
    repo.put_source_text(story)
    MEMORY_PROJECT_INDEX.add(project_id)
    Pipeline(repo=repo, cfg=cfg).ingest_story(story)
    return format_graph_snapshot(repo, cfg)


def list_production_projects(archived: bool = False) -> list[dict[str, Any]]:
    """Return snapshots of all registered productions filtered by archived status."""
    cfg = load_runtime_config()
    results: list[dict[str, Any]] = []
    for pid in sorted(MEMORY_PROJECT_INDEX):
        repo = get_repo(pid, cfg=cfg)
        meta = repo.get_project_meta()
        if not meta or (not archived and meta.archived):
            continue
        results.append(format_graph_snapshot(repo, cfg))
    results.sort(key=lambda r: r.get("updatedAt", 0), reverse=True)
    return results


def get_production_project(project_id: str) -> dict[str, Any]:
    """Return the full StoryGraph snapshot for `project_id`."""
    cfg = load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    return format_graph_snapshot(repo, cfg)


def update_production_project(
    project_id: str, updates: dict[str, Any]
) -> dict[str, Any]:
    """Patch allowed ProjectMeta fields and synchronize source text if changed."""
    cfg = load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    meta = repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")
    patch_dict = {
        k: v for k, v in updates.items() if k in _ALLOWED_PATCH_FIELDS and v is not None
    }
    patch_dict["updated_at"] = datetime.now(UTC)
    repo.put_project_meta(meta.model_copy(update=patch_dict))
    if "base_concept" in patch_dict or "story_text" in patch_dict:
        repo.put_source_text(
            str(patch_dict.get("story_text") or patch_dict.get("base_concept"))
        )
    return format_graph_snapshot(repo, cfg)


def run_pipeline_for_project(
    project_id: str, body: RunPipelinePayload | None = None
) -> dict[str, Any]:
    """Run the StoryGraph pipeline forward until blocked by an unapproved gate or completed."""
    pipe = build_pipeline(project_id)
    meta = pipe.repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")
    if body and body.reset:
        reset_storygraph_collections(pipe.repo)
    blocked_gate: str | None = None
    try:
        pipe.run_until_gate_or_done(
            story_text=body.story_text if body else None,
            auto_approve_gates=body.auto_approve_gates if body else None,
        )
    except GateBlocked as gb:
        blocked_gate = gb.gate_id
        cur = pipe.repo.get_project_meta() or meta
        pipe.repo.put_project_meta(
            cur.model_copy(
                update={
                    "status": f"awaiting_{gb.gate_id.lower()}",
                    "updated_at": datetime.now(UTC),
                }
            )
        )
    except (ValidationFailed, BudgetExceeded, PermissionDenied, StoryGraphError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    snap = format_graph_snapshot(pipe.repo, pipe.cfg)
    snap["blocked_gate"] = blocked_gate
    return snap


def analyze_project_compat(
    project_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compatibility helper for triggering initial story expansion & world extraction."""
    payload = body or {}
    if payload:
        update_production_project(project_id, payload)
    snap = run_pipeline_for_project(
        project_id,
        RunPipelinePayload(
            auto_approve_gates=payload.get("auto_approve_gates"),
            story_text=payload.get("base_concept"),
        ),
    )
    return {
        "data": {"scenes": snap["scenes"], "story_graph": snap["story_graph"]},
        "usage": snap["total_usage"],
        "production": snap,
    }


def render_project_compat(
    project_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Run the production forward (auto-approving gates by default)."""
    auto_approve = (body or {}).get("auto_approve_gates", True)
    return run_pipeline_for_project(
        project_id, RunPipelinePayload(auto_approve_gates=auto_approve)
    )


def _clear_rendered_runs(pipe: Pipeline) -> None:
    """Remove prior GenerationRun records and extracted last-frame assets before a forced re-render."""
    for run in pipe.repo.list_generation_runs():
        pipe.repo.store.delete("generation_runs", run.id)
        pipe.repo.store.delete("assets", f"ast_lastframe_{run.shot_id}")


def _execute_requested_stage(pipe: Pipeline, st: Stage, force: bool) -> None:
    """Execute a specific stage on `pipe`, handling forced S1 reset and S8 cascade."""
    if st == Stage.S1_EXTRACT and force:
        reset_storygraph_collections(pipe.repo)
        pipe.run_stage(Stage.S1_EXTRACT, force=True)
        return
    if st == Stage.S4_SHOTS and force:
        _clear_rendered_runs(pipe)
    if st == Stage.S8_RENDER and force:
        _clear_rendered_runs(pipe)
        for sh in pipe.repo.list_shots():
            pipe.repo.put_shot(
                sh.model_copy(
                    update={"stale": True, "stale_reason": "Manual re-render requested"}
                )
            )
        for cascade_st in (Stage.S8_RENDER, Stage.S9_QA, Stage.S10_ASSEMBLE):
            pipe.run_stage(cascade_st, force=True)
        return
    pipe.run_stage(st, force=force)


def run_project_stage(
    project_id: str, stage_id: str, force: bool = True
) -> dict[str, Any]:
    """Run a single StoryGraph stage (`S1_EXTRACT` .. `S10_ASSEMBLE`)."""
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    try:
        st = Stage(stage_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage_id}'")
    try:
        _execute_requested_stage(pipe, st, force)
    except GateBlocked as gb:
        raise HTTPException(
            status_code=409,
            detail=f"Stage {stage_id} blocked by unapproved gate {gb.gate_id}",
        )
    except (ValidationFailed, BudgetExceeded, PermissionDenied, StoryGraphError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return format_graph_snapshot(pipe.repo, pipe.cfg)


def approve_project_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
    advance: bool = True,
) -> dict[str, Any]:
    """Approve gate `G1`, `G2`, or `G3` and optionally advance the pipeline."""
    if gate_id not in ("G1", "G2", "G3"):
        raise HTTPException(status_code=400, detail=f"Invalid gate_id '{gate_id}'")
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    decision = body or GateDecisionPayload()
    approve_gate(
        pipe.repo,
        gate_id=gate_id,  # type: ignore[arg-type]
        reviewer=decision.reviewer,
        notes=decision.notes,
    )
    if advance:
        return run_pipeline_for_project(project_id)
    return format_graph_snapshot(pipe.repo, pipe.cfg)


def reject_project_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
) -> dict[str, Any]:
    """Reject gate `G1`, `G2`, or `G3` with reviewer notes."""
    if gate_id not in ("G1", "G2", "G3"):
        raise HTTPException(status_code=400, detail=f"Invalid gate_id '{gate_id}'")
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    decision = body or GateDecisionPayload()
    reject_gate(
        pipe.repo,
        gate_id=gate_id,  # type: ignore[arg-type]
        reviewer=decision.reviewer,
        notes=decision.notes or "Revision requested",
    )
    return format_graph_snapshot(pipe.repo, pipe.cfg)


def approve_project_appearance(project_id: str, appearance_id: str) -> dict[str, Any]:
    """Approve an individual Appearance and its associated Assets."""
    cfg = load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    app_node = repo.get_appearance(appearance_id)
    if not app_node:
        raise HTTPException(
            status_code=404, detail=f"Appearance {appearance_id} not found"
        )
    repo.update_appearance_status(appearance_id, Status.APPROVED)
    for aid in app_node.asset_ids:
        repo.update_asset(aid, status=Status.APPROVED)
    return format_graph_snapshot(repo, cfg)


def regenerate_project_appearance(
    project_id: str, appearance_id: str
) -> dict[str, Any]:
    """Re-run the Visual Design Studio for the entity depicted by `appearance_id`."""
    pipe = build_pipeline(project_id)
    app_node = pipe.repo.get_appearance(appearance_id)
    if not app_node:
        raise HTTPException(
            status_code=404, detail=f"Appearance {appearance_id} not found"
        )
    design_single_entity(
        pipe.repo,
        pipe.cfg,
        entity_id=app_node.entity_id,
        image_gen=pipe.image_gen,
        vlm=pipe.vlm,
        force_regenerate=True,
    )
    return format_graph_snapshot(pipe.repo, pipe.cfg)


def compile_project_shot_preview(project_id: str, shot_id: str) -> dict[str, Any]:
    """Preview the deterministic RefPlan and compiled Package prompt for `shot_id`."""
    pipe = build_pipeline(project_id)
    try:
        sv = shot_view(pipe.repo, shot_id)
        plan = select_references(sv, pipe.cfg, caps=pipe.video_gen.caps, repo=pipe.repo)
        pkg = compile_shot(
            sv,
            plan,
            pipe.cfg,
            caps=pipe.video_gen.caps,
            project_id=project_id,
            attempt=1,
        )
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf))
    except StoryGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "shot_id": pkg.shot_id,
        "compiled_prompt": pkg.compiled_prompt,
        "negative_prompt": pkg.negative_prompt,
        "reference_asset_ids": pkg.reference_asset_ids,
        "first_frame_asset_id": pkg.first_frame_asset_id,
        "dropped_to_verbal": pkg.dropped_to_verbal,
        "candidate_scores": plan.candidate_scores,
        "duration_s": pkg.duration_s,
        "aspect_ratio": pkg.aspect_ratio,
        "seed": pkg.seed,
        "package_hash": pkg.package_hash,
    }

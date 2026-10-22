"""Design-review and compile-preview operations for StoryGraph Productions endpoints.

Split out of `productions_service` (file-size limit); routers keep importing these names
from `services.productions_service`, which re-exports them unchanged.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import HTTPException
from storygraph.agents.design_studio import design_single_entity
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.errors import NotFound, StoryGraphError
from storygraph.schema import Status
from storygraph.views import shot_view

from .runtime import build_pipeline, get_repo, load_runtime_config
from .snapshot import format_graph_snapshot


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
    meta = pipe.repo.get_project_meta()
    is_final = bool(
        meta and (meta.render_quality == "final" or meta.video_resolution == "720p")
    )
    res = "720p" if is_final else "360p"
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
            resolution=res,
        )
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf))
    except StoryGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {**asdict(pkg), "candidate_scores": plan.candidate_scores}

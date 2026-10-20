"""Production CRUD, brief analysis, standalone review/eval, and StoryGraph bridge endpoints."""

from __future__ import annotations

import logging
from typing import Any

import deps
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from helpers import sign_production_urls
from models import AIResponseWrapper, Project, ProjectStatus

from routers._crud import register_crud_routes
from routers.render_helpers import (
    run_standalone_regenerate_flagged,
    run_storyboard_review_step,
    run_video_eval_step,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["productions"])


def _prod_log(
    where: str, what: str, why: str, how: str = "productions_router"
) -> dict[str, str]:
    """Build structured 5W1H telemetry context for production routes."""
    return {
        "who": "productions_router",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


register_crud_routes(
    router,
    resource_label="Production",
    getter=lambda rid: deps.firestore_svc.get_production(rid),
    updater=lambda rid, u: deps.firestore_svc.update_production(rid, u),
    deleter=lambda rid: deps.firestore_svc.update_production(rid, {"archived": True}),
    lister=lambda include_archived=False: deps.firestore_svc.get_productions(
        include_archived=include_archived
    ),
    sign_one=sign_production_urls,
    sign_list=lambda p: sign_production_urls(p, thumbnails_only=True),
    include_patch=True,
    include_delete=True,
    include_unarchive=True,
)


@router.post("", response_model=Project)
async def create_production(request: Request, project: Project) -> Project:
    """Create a new production project in Firestore."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    project.invite_code = getattr(request.state, "invite_code", None)
    deps.firestore_svc.create_production(project)
    return project


def _apply_brief_fields(p: Project, body: dict[str, Any]) -> dict[str, Any]:
    """Mutate `p` with brief fields from `body` and return the Firestore update dict."""
    field_updates: dict[str, Any] = {"status": ProjectStatus.ANALYZING}
    fields = (
        "name",
        "type",
        "base_concept",
        "video_length",
        "orientation",
        "language",
        "reference_image_url",
        "visual_style_preset",
        "color_palette_preset",
        "director_style_preset",
        "screenplay_style_preset",
        "music_style_preset",
    )
    for field in fields:
        val = body.get(field)
        if val is not None and val != "":
            setattr(p, field, val)
            field_updates[field] = val
    return field_updates


@router.post("/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(
    request: Request, id: str, body: dict[str, Any] = {}
) -> Any:
    """Analyze a production brief and generate storyboard scenes."""
    _ = request
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    deps.firestore_svc.update_production(id, _apply_brief_fields(p, body))
    try:
        result = await deps.ai_svc.analyze_brief(
            id,
            p.base_concept,
            p.video_length,
            p.orientation,
            prompt_id=body.get("prompt_id"),
            schema_id=body.get("schema_id"),
            project_type=p.type,
            project=p,
            model_id=body.get("model_id"),
            region=body.get("region"),
        )
    except Exception as e:
        logger.error(
            f"Analysis failed for production {id}: {e}",
            extra=_prod_log("analyze_production", "analysis_failed", str(e)),
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))
    updates = _build_analyze_updates(
        result, body.get("prompt_id"), body.get("schema_id")
    )
    deps.firestore_svc.update_production(id, updates)
    return result


@router.post("/{id}/review")
async def review_production_storyboard(request: Request, id: str) -> dict[str, Any]:
    """Run Stage 1 Storyboard Continuity & Realism Review standalone."""
    _ = request
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    prev_status = (
        p.status
        if p.status in (ProjectStatus.COMPLETED, ProjectStatus.SCRIPTED)
        else ProjectStatus.SCRIPTED
    )
    try:
        await run_storyboard_review_step(id, production=p)
        deps.firestore_svc.update_production(id, {"status": prev_status})
    except Exception as e:
        logger.error(
            f"Storyboard review failed for production {id}: {e}",
            extra=_prod_log("review_production_storyboard", "review_failed", str(e)),
        )
        deps.firestore_svc.update_production(
            id, {"status": prev_status, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))
    updated = deps.firestore_svc.get_production(id) or p
    return sign_production_urls(updated)


@router.post("/{id}/evaluate")
async def evaluate_production_video(request: Request, id: str) -> dict[str, Any]:
    """Run Stage 4 Multimodal Finished-Video Evaluation standalone."""
    _ = request
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    iteration = (p.eval_report.iteration + 1) if p.eval_report else 1
    try:
        await run_video_eval_step(id, production=p, iteration=iteration)
        deps.firestore_svc.update_production(id, {"status": ProjectStatus.COMPLETED})
    except Exception as e:
        logger.error(
            f"Video evaluation failed for production {id}: {e}",
            extra=_prod_log("evaluate_production_video", "eval_failed", str(e)),
        )
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.COMPLETED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))
    updated = deps.firestore_svc.get_production(id) or p
    return sign_production_urls(updated)


@router.post("/{id}/regenerate-flagged")
async def regenerate_flagged_production_scenes(
    request: Request, id: str, background_tasks: BackgroundTasks
) -> dict[str, str]:
    """Run Stage 5 Selective Auto-Regeneration & Re-Stitch on flagged scenes."""
    _ = request
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    deps.firestore_svc.update_production(
        id, {"status": ProjectStatus.REGENERATING, "error_message": None}
    )
    background_tasks.add_task(run_standalone_regenerate_flagged, id)
    return {"status": "regenerating"}


def _build_analyze_updates(
    result: Any, prompt_id: str | None, schema_id: str | None
) -> dict[str, Any]:
    """Assemble Firestore updates from analyze_brief result + optional resource IDs."""
    data = result.data
    updates: dict[str, Any] = {
        "scenes": [s.dict() for s in data["scenes"]],
        "status": ProjectStatus.SCRIPTED,
        "total_usage": result.usage.dict(),
    }
    for key in ("global_style", "continuity", "analysis_prompt"):
        if data.get(key):
            updates[key] = data[key]
    for resource_id, info_key in (
        (prompt_id, "prompt_info"),
        (schema_id, "schema_info"),
    ):
        if resource_id:
            res = deps.firestore_svc.get_resource(resource_id)
            if res:
                updates[info_key] = {
                    "id": res.id,
                    "name": res.name,
                    "version": res.version,
                }
    return updates


def _load_storygraph_service() -> Any:
    """Lazy-load the StoryGraph service functions from `productions_service`."""
    import importlib.util
    import sys
    from pathlib import Path

    if "productions_service_main" in sys.modules:
        return sys.modules["productions_service_main"]
    prod_svc_dir = (
        Path(__file__).resolve().parent.parent.parent.parent / "productions_service"
    )
    if str(prod_svc_dir) not in sys.path:
        sys.path.insert(0, str(prod_svc_dir))
    main_path = prod_svc_dir / "main.py"
    spec = importlib.util.spec_from_file_location("productions_service_main", main_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load StoryGraph service from {main_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["productions_service_main"] = module
    spec.loader.exec_module(module)
    return module


def _ensure_storygraph_seeded(id: str) -> Any:
    """Ensure the StoryGraph repository is seeded with project metadata from Firestore."""
    prod_main = _load_storygraph_service()
    cfg = prod_main._load_runtime_config()
    repo = prod_main.get_repo(id, cfg=cfg)
    if not repo.get_project_meta() and deps.firestore_svc:
        p = deps.firestore_svc.get_production(id)
        if p:
            from storygraph.presets import resolve_production_presets
            from storygraph.schema import ProjectMeta

            ptype = (
                p.type if p.type in ("movie", "advertizement", "social") else "movie"
            )
            orient = p.orientation if p.orientation in ("16:9", "9:16") else "16:9"
            lang = getattr(p, "language", "en-IN") or "en-IN"
            resolved = resolve_production_presets(
                getattr(p, "visual_style_preset", None),
                getattr(p, "color_palette_preset", None),
                getattr(p, "director_style_preset", None),
                getattr(p, "screenplay_style_preset", None),
                getattr(p, "music_style_preset", None),
            )
            meta = ProjectMeta(
                id=p.id,
                name=p.name,
                type=ptype,
                base_concept=p.base_concept,
                story_text=p.base_concept,
                video_length=str(p.video_length),
                orientation=orient,
                language=lang,
                visual_style_preset=resolved.visual_style.id,
                color_palette_preset=resolved.color_palette.id,
                director_style_preset=resolved.director_style.id,
                screenplay_style_preset=resolved.screenplay_style.id,
                music_style_preset=resolved.music_style.id,
            )
            repo.put_project_meta(meta)
            repo.put_source_text(p.base_concept)
            prod_main.Pipeline(repo=repo, cfg=cfg).ingest_story(p.base_concept)
            prod_main._MEMORY_PROJECT_INDEX.add(p.id)
    return prod_main


@router.get("/{id}/graph")
async def get_production_story_graph(id: str) -> Any:
    """Return the StoryGraph representation for a production."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.get_production(id)


@router.post("/{id}/run")
async def run_story_graph_pipeline(id: str, body: dict[str, Any] = {}) -> Any:
    """Execute the StoryGraph pipeline for a production."""
    prod_main = _ensure_storygraph_seeded(id)
    payload = prod_main.RunPipelinePayload(
        auto_approve_gates=body.get("auto_approve_gates"),
        story_text=body.get("story_text"),
    )
    return await prod_main.run_production_pipeline(id, payload)


@router.post("/{id}/stages/{stage_id}/run")
async def run_story_graph_stage(
    id: str, stage_id: str, force: bool = True, quality: str | None = None
) -> Any:
    """Run a single StoryGraph stage for a production."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.run_single_stage(id, stage_id, force=force, quality=quality)


@router.post("/{id}/gates/{gate_id}/approve")
async def approve_story_graph_gate(
    id: str, gate_id: str, body: dict[str, Any] = {}
) -> Any:
    """Approve a StoryGraph review gate."""
    prod_main = _ensure_storygraph_seeded(id)
    payload = prod_main.GateDecisionPayload(
        reviewer=body.get("reviewer", "studio_user"),
        notes=body.get("notes"),
    )
    return await prod_main.approve_production_gate(id, gate_id, payload)


@router.post("/{id}/gates/{gate_id}/reject")
async def reject_story_graph_gate(
    id: str, gate_id: str, body: dict[str, Any] = {}
) -> Any:
    """Reject a StoryGraph review gate with revision notes."""
    prod_main = _ensure_storygraph_seeded(id)
    payload = prod_main.GateDecisionPayload(
        reviewer=body.get("reviewer", "studio_user"),
        notes=body.get("notes", "Revision requested"),
    )
    return await prod_main.reject_production_gate(id, gate_id, payload)


@router.post("/{id}/appearances/{appearance_id}/approve")
async def approve_story_graph_appearance(id: str, appearance_id: str) -> Any:
    """Approve a character appearance in the StoryGraph."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.approve_single_appearance(id, appearance_id)


@router.post("/{id}/appearances/{appearance_id}/regenerate")
async def regenerate_story_graph_appearance(id: str, appearance_id: str) -> Any:
    """Regenerate a character appearance in the StoryGraph."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.regenerate_single_appearance(id, appearance_id)


@router.post("/{id}/shots/{shot_id}/compile")
async def compile_story_graph_shot(id: str, shot_id: str) -> Any:
    """Compile preview prompts for a single StoryGraph shot."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.compile_single_shot_preview(id, shot_id)


@router.get("/{id}/assembly-readiness")
async def get_story_graph_assembly_readiness(id: str) -> Any:
    """Return ready vs blocking shots for final assembly."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.get_production_assembly_readiness(id)


@router.post("/{id}/assemble")
async def assemble_story_graph_production(id: str, mode: str = "approved_only") -> Any:
    """Stitch the final video (`approved_only` skips blocking shots; `strict` requires all)."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.assemble_production(id, mode)


@router.post("/{id}/shots/repair")
async def repair_story_graph_shots(id: str, body: dict[str, Any] | None = None) -> Any:
    """Auto-repair blocking shots (2 directed attempts each), then strict-assemble if ready."""
    prod_main = _ensure_storygraph_seeded(id)
    payload = prod_main.RepairShotsPayload(shot_ids=(body or {}).get("shot_ids"))
    return await prod_main.repair_production_shots(id, payload)


@router.patch("/{id}/shots/{shot_id}/clip")
async def edit_story_graph_shot_clip(
    id: str, shot_id: str, body: dict[str, Any] | None = None
) -> Any:
    """Edit a shot's clip prompt / step actions (marks the shot stale, resets repairs)."""
    prod_main = _ensure_storygraph_seeded(id)
    payload = prod_main.ClipEdit.model_validate(body or {})
    return await prod_main.edit_production_shot_clip(id, shot_id, payload)


@router.post("/{id}/shots/{shot_id}/regenerate")
async def regenerate_story_graph_shot(id: str, shot_id: str) -> Any:
    """Re-render one shot (+ continuity followers) with QA and repairs."""
    prod_main = _ensure_storygraph_seeded(id)
    return await prod_main.regenerate_production_shot(id, shot_id)

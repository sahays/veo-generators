import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import deps
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


register_crud_routes(
    router,
    resource_label="Production",
    getter=lambda rid: deps.firestore_svc.get_production(rid),
    updater=lambda rid, u: deps.firestore_svc.update_production(rid, u),
    lister=lambda include_archived=False: deps.firestore_svc.get_productions(
        include_archived=include_archived
    ),
    sign_one=sign_production_urls,
    sign_list=lambda p: sign_production_urls(p, thumbnails_only=True),
    include_patch=True,
    include_delete=False,
    include_unarchive=True,
)


@router.post("", response_model=Project)
async def create_production(request: Request, project: Project):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    project.invite_code = getattr(request.state, "invite_code", None)
    deps.firestore_svc.create_production(project)
    return project


@router.post("/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(request: Request, id: str, body: dict = {}):
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)

    field_updates: dict = {"status": ProjectStatus.ANALYZING}
    for field in (
        "name",
        "type",
        "base_concept",
        "video_length",
        "orientation",
        "language",
        "reference_image_url",
    ):
        val = body.get(field)
        if val is not None and val != "":
            setattr(p, field, val)
            field_updates[field] = val

    deps.firestore_svc.update_production(id, field_updates)
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
        logger.error(f"Analysis failed for production {id}: {e}")
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
async def review_production_storyboard(request: Request, id: str):
    """Run Stage 1 Storyboard Continuity & Realism Review standalone."""
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
        logger.error(f"Storyboard review failed for production {id}: {e}")
        deps.firestore_svc.update_production(
            id, {"status": prev_status, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))
    updated = deps.firestore_svc.get_production(id) or p
    return sign_production_urls(updated)


@router.post("/{id}/evaluate")
async def evaluate_production_video(request: Request, id: str):
    """Run Stage 4 Multimodal Finished-Video Evaluation standalone."""
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
        logger.error(f"Video evaluation failed for production {id}: {e}")
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.COMPLETED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))
    updated = deps.firestore_svc.get_production(id) or p
    return sign_production_urls(updated)


@router.post("/{id}/regenerate-flagged")
async def regenerate_flagged_production_scenes(
    request: Request, id: str, background_tasks: BackgroundTasks
):
    """Run Stage 5 Selective Auto-Regeneration & Re-Stitch on flagged scenes."""
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


def _build_analyze_updates(result, prompt_id, schema_id) -> dict:
    """Assemble Firestore updates from analyze_brief result + optional resource IDs."""
    data = result.data
    updates: dict = {
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

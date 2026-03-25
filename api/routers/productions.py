import logging

from fastapi import APIRouter, HTTPException, Request

import deps
from helpers import sign_production_urls
from models import Project, ProjectStatus, AIResponseWrapper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/productions", tags=["productions"])


@router.get("")
async def list_productions(request: Request, archived: bool = False):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    productions = deps.firestore_svc.get_productions(include_archived=archived)
    return [sign_production_urls(p, thumbnails_only=True) for p in productions]


@router.post("", response_model=Project)
async def create_production(request: Request, project: Project):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    project.invite_code = getattr(request.state, "invite_code", None)
    deps.firestore_svc.create_production(project)
    return project


@router.get("/{id}")
async def get_production(id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    return sign_production_urls(p)


@router.post("/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(request: Request, id: str, body: dict = {}):
    if not deps.firestore_svc or not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)

    prompt_id = body.get("prompt_id")
    schema_id = body.get("schema_id")

    deps.firestore_svc.update_production(id, {"status": ProjectStatus.ANALYZING})
    try:
        result = await deps.ai_svc.analyze_brief(
            id,
            p.base_concept,
            p.video_length,
            p.orientation,
            prompt_id=prompt_id,
            schema_id=schema_id,
            project_type=p.type,
            project=p,
        )
    except Exception as e:
        logger.error(f"Analysis failed for production {id}: {e}")
        deps.firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))

    result_data = result.data

    # Resolve names/versions for badges if IDs were provided
    prompt_info = None
    if prompt_id:
        res = deps.firestore_svc.get_resource(prompt_id)
        if res:
            prompt_info = {"id": res.id, "name": res.name, "version": res.version}

    schema_info = None
    if schema_id:
        res = deps.firestore_svc.get_resource(schema_id)
        if res:
            schema_info = {"id": res.id, "name": res.name, "version": res.version}

    updates = {
        "scenes": [s.dict() for s in result_data["scenes"]],
        "status": ProjectStatus.SCRIPTED,
        "total_usage": result.usage.dict(),
    }
    if result_data.get("global_style"):
        updates["global_style"] = result_data["global_style"]
    if result_data.get("continuity"):
        updates["continuity"] = result_data["continuity"]
    if result_data.get("analysis_prompt"):
        updates["analysis_prompt"] = result_data["analysis_prompt"]
    if prompt_info:
        updates["prompt_info"] = prompt_info
    if schema_info:
        updates["schema_info"] = schema_info

    deps.firestore_svc.update_production(id, updates)
    return result


@router.post("/{id}/archive")
async def archive_production(id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    deps.firestore_svc.update_production(id, {"archived": True})
    return {"status": "archived"}


@router.post("/{id}/unarchive")
async def unarchive_production(id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = deps.firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    deps.firestore_svc.update_production(id, {"archived": False})
    return {"status": "unarchived"}

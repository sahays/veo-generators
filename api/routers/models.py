from typing import List

from fastapi import APIRouter, HTTPException, Request

import deps
from models import AIModel, CreateAIModelRequest, AVAILABLE_REGIONS
from routers.auth import _require_master

router = APIRouter(prefix="/api/v1/models", tags=["models"])

SEED_MODELS = [
    # Text Analysis
    {
        "name": "Gemini 3.8 Flash",
        "code": "gemini-3.8-flash",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global", "us"],
        "is_default": True,
    },
    {
        "name": "Gemini 3.7 Flash",
        "code": "gemini-3.7-flash",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global", "us"],
    },
    {
        "name": "Gemini 3.5 Flash",
        "code": "gemini-3.5-flash",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global", "us"],
    },
    {
        "name": "Gemini 3.5 Flash-Lite",
        "code": "gemini-3.5-flash-lite",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global", "us"],
    },
    {
        "name": "Gemini 3.1 Pro",
        "code": "gemini-3.1-pro-preview",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global"],
    },
    {
        "name": "Gemini 3 Flash",
        "code": "gemini-3-flash-preview",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global"],
    },
    {
        "name": "Gemini 3.1 Flash-Lite",
        "code": "gemini-3.1-flash-lite",
        "provider": "gemini",
        "capability": "text",
        "regions": ["global"],
    },
    # Image Generation
    {
        "name": "Gemini Nano Banana 2.1",
        "code": "gemini-nano-banana-2.1",
        "provider": "gemini",
        "capability": "image",
        "regions": ["global"],
        "is_default": True,
    },
    {
        "name": "Gemini 3.1 Flash Image (Nano Banana 2)",
        "code": "gemini-3.1-flash-image",
        "provider": "gemini",
        "capability": "image",
        "regions": ["global"],
    },
    {
        "name": "Gemini 3.1 Flash-Lite Image",
        "code": "gemini-3.1-flash-lite-image",
        "provider": "gemini",
        "capability": "image",
        "regions": ["global"],
    },
    {
        "name": "Gemini 3 Pro Image (Nano Banana Pro)",
        "code": "gemini-3-pro-image",
        "provider": "gemini",
        "capability": "image",
        "regions": ["global"],
    },
    {
        "name": "Gemini 3.1 Flash Image (Preview)",
        "code": "gemini-3.1-flash-image-preview",
        "provider": "gemini",
        "capability": "image",
        "regions": ["global"],
    },
    # Video Generation
    {
        "name": "Gemini Omni 1.1 Flash",
        "code": "gemini-omni-1.1-flash-preview",
        "provider": "gemini",
        "capability": "video",
        "regions": ["global"],
        "is_default": True,
    },
    {
        "name": "Gemini Omni Flash (Alias)",
        "code": "gemini-omni-flash-preview",
        "provider": "gemini",
        "capability": "video",
        "regions": ["global"],
    },
    {
        "name": "Veo 3.1 Generate",
        "code": "veo-3.1-generate-001",
        "provider": "veo",
        "capability": "video",
        "regions": ["global"],
    },
    {
        "name": "Veo 3.1 Fast",
        "code": "veo-3.1-fast-generate-001",
        "provider": "veo",
        "capability": "video",
        "regions": ["global"],
    },
    {
        "name": "Veo 3.1 Lite",
        "code": "veo-3.1-lite-generate-001",
        "provider": "veo",
        "capability": "video",
        "regions": ["global"],
    },
]


@router.get("", response_model=List[AIModel])
async def list_models():
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return deps.firestore_svc.get_ai_models()


@router.get("/defaults")
async def get_model_defaults():
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    result = {}
    for cap in ("text", "image", "video"):
        m = deps.firestore_svc.get_default_model(cap)
        if m:
            regions = m.regions or ["global"]
            result[cap] = {
                "id": m.id,
                "name": m.name,
                "code": m.code,
                "regions": regions,
                "region": regions[0],
            }
        else:
            seed = next(
                (
                    s
                    for s in SEED_MODELS
                    if s["capability"] == cap and s.get("is_default")
                ),
                None,
            )
            if seed:
                regions = seed.get("regions") or ["global"]
                result[cap] = {
                    "id": "",
                    "name": seed["name"],
                    "code": seed["code"],
                    "regions": regions,
                    "region": regions[0],
                }
            else:
                result[cap] = None
    return result


@router.get("/regions")
async def list_regions():
    return AVAILABLE_REGIONS


@router.post("", response_model=AIModel)
async def create_model(body: CreateAIModelRequest, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    model = AIModel(
        name=body.name,
        code=body.code,
        provider=body.provider,
        capability=body.capability,
        regions=body.regions,
        is_default=body.is_default,
    )
    deps.firestore_svc.create_ai_model(model)
    if body.is_default:
        deps.firestore_svc.set_model_default(model.id)
    return model


@router.post("/{model_id}/set-default")
async def set_model_default(model_id: str, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    model = deps.firestore_svc.get_ai_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    deps.firestore_svc.set_model_default(model_id)
    return {"status": "success"}


@router.patch("/{model_id}")
async def update_model(model_id: str, body: dict, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    model = deps.firestore_svc.get_ai_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    allowed = {"name", "code", "provider", "capability", "regions", "is_active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        deps.firestore_svc.update_ai_model(model_id, updates)
    return {"status": "updated"}


@router.delete("/{model_id}")
async def delete_model(model_id: str, request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    model = deps.firestore_svc.get_ai_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    deps.firestore_svc.delete_ai_model(model_id)
    return {"status": "deleted"}


@router.post("/seed")
async def seed_models(request: Request):
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    existing = deps.firestore_svc.get_ai_models()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Models already exist. Delete them first to re-seed.",
        )
    created = []
    for seed in SEED_MODELS:
        model = AIModel(**seed)
        deps.firestore_svc.create_ai_model(model)
        created.append(model)
    return {"status": "seeded", "count": len(created)}

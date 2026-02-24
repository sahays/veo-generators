from typing import List, Optional

from fastapi import APIRouter, HTTPException

import deps
from models import SystemResource

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/resources", response_model=List[SystemResource])
async def list_system_resources(
    type: Optional[str] = None, category: Optional[str] = None
):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return deps.firestore_svc.list_resources(resource_type=type, category=category)


@router.post("/resources", response_model=SystemResource)
async def create_system_resource(resource: SystemResource):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    deps.firestore_svc.create_resource(resource)
    return resource


@router.post("/resources/{id}/activate")
async def activate_system_resource(id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    deps.firestore_svc.set_resource_active(id)
    return {"status": "success"}


@router.get("/default-schema")
async def get_default_schema():
    from ai_service import _load_default_schema

    return _load_default_schema()

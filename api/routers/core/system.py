"""System resource management and agent-discoverable lookup endpoints."""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request

import deps
from models import SystemResource
from routers.core.auth import _require_master

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/resources", response_model=List[SystemResource])
async def list_system_resources(
    type: Optional[str] = None, category: Optional[str] = None
) -> list[SystemResource]:
    """List system prompts and schemas filtered by type and category."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return deps.firestore_svc.list_resources(resource_type=type, category=category)


@router.post("/resources", response_model=SystemResource)
async def create_system_resource(
    resource: SystemResource, request: Request
) -> SystemResource:
    """Create a new system prompt or schema resource (master access required)."""
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    deps.firestore_svc.create_resource(resource)
    return resource


@router.get("/resources/{id}", response_model=SystemResource)
async def get_system_resource(id: str) -> SystemResource:
    """Fetch a single system resource by ID."""
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    resource = deps.firestore_svc.get_resource(id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.post("/resources/{id}/activate")
async def activate_system_resource(id: str, request: Request) -> dict[str, str]:
    """Mark a system resource as active for its category."""
    _require_master(request)
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    deps.firestore_svc.set_resource_active(id)
    return {"status": "success"}


@router.get("/default-schema")
async def get_default_schema() -> Any:
    """Return the built-in default production JSON schema."""
    from ai_helpers import load_schema

    return load_schema("production-schema")


@router.get("/lookups/content-types")
async def list_content_types() -> list[dict[str, Any]]:
    """Return valid content types for video reframing."""
    from reframe_strategies import CONTENT_TYPE_VARIABLES, STRATEGY_CONFIG

    return [
        {
            "id": ct,
            "description": vars.get("content_description", ct),
            "cv_strategy": STRATEGY_CONFIG.get(ct, {}).get("cv_strategy", "face"),
        }
        for ct, vars in CONTENT_TYPE_VARIABLES.items()
    ]


@router.get("/lookups/aspect-ratios")
async def list_aspect_ratios() -> dict[str, Any]:
    """Return valid aspect ratios and preset bundles for adapts."""
    from routers.adapts import ALL_RATIOS, PRESET_BUNDLES

    return {
        "ratios": ALL_RATIOS,
        "preset_bundles": {
            k: {"name": v["name"], "ratios": v["ratios"]}
            for k, v in PRESET_BUNDLES.items()
        },
    }


@router.get("/lookups/prompt-categories")
async def list_prompt_categories() -> list[dict[str, Any]]:
    """Return distinct prompt categories with sample prompt names."""
    if not deps.firestore_svc:
        return []
    resources = deps.firestore_svc.list_resources(resource_type="prompt")
    by_cat: dict[str, list[str]] = {}
    for r in resources:
        if r.category:
            by_cat.setdefault(r.category, []).append(r.name)
    return [
        {"id": cat, "count": len(names), "examples": names[:3]}
        for cat, names in sorted(by_cat.items())
    ]

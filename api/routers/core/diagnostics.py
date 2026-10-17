"""Diagnostic endpoints for prompt optimization, frame generation, and video polling."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

import deps
from models import ProjectStatus, Scene

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


@router.post("/optimize-prompt")
async def diagnostic_optimize(request: Request, body: dict[str, Any]) -> Any:
    """Run brief analysis on a diagnostic concept payload."""
    _ = request
    if not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await deps.ai_svc.analyze_brief(
        "diag-proj",
        body.get("concept", ""),
        body.get("length", "16"),
        body.get("orientation", "16:9"),
    )


@router.post("/generate-image")
async def diagnostic_image(request: Request, body: dict[str, Any]) -> Any:
    """Generate a single diagnostic keyframe image."""
    _ = request
    if not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    scene = Scene(
        visual_description=body.get("prompt", ""),
        timestamp_start="0",
        timestamp_end="8",
    )
    return await deps.ai_svc.generate_frame(
        "diag-proj", scene, body.get("orientation", "16:9")
    )


@router.post("/generate-video")
async def diagnostic_video(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Generate a single diagnostic video clip."""
    _ = request
    if not deps.video_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    scene = Scene(
        visual_description=body.get("prompt", ""),
        timestamp_start="0",
        timestamp_end="8",
    )
    result = await deps.video_svc.generate_scene_video(
        "diag-proj", scene, blocking=False
    )
    if isinstance(result, dict) and "operation_name" in result:
        return result
    return {
        "video_uri": result,
        "signed_url": deps.storage_svc.get_signed_url(result) if result else None,
    }


def _record_operation_failure(
    production_id: str, scene_id: Optional[str], status: dict[str, Any]
) -> None:
    """Persist failed operation state to scene and production in Firestore."""
    error_msg = (
        status.get("error") or status.get("message") or "Video generation failed"
    )
    if scene_id:
        deps.firestore_svc.update_scene(
            production_id,
            scene_id,
            {"status": "failed", "error_message": str(error_msg)},
        )
    deps.firestore_svc.update_production(
        production_id,
        {
            "status": ProjectStatus.FAILED,
            "error_message": f"Video generation failed for scene {scene_id or 'unknown'}: {error_msg}",
        },
    )


@router.get("/operations/{name:path}")
async def check_operation_status(
    name: str,
    production_id: Optional[str] = None,
    scene_id: Optional[str] = None,
) -> dict[str, Any]:
    """Check the status of a long-running video generation operation."""
    if not deps.video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    status = await deps.video_svc.get_video_generation_status(name)
    if status.get("status") == "completed" and status.get("video_uri"):
        status["signed_url"] = deps.storage_svc.get_signed_url(status["video_uri"])
        if production_id and scene_id and deps.firestore_svc:
            deps.firestore_svc.update_scene(
                production_id,
                scene_id,
                {"status": "completed", "video_url": status["video_uri"]},
            )
    elif (
        status.get("status") in ("failed", "error")
        and production_id
        and deps.firestore_svc
    ):
        _record_operation_failure(production_id, scene_id, status)
    return status

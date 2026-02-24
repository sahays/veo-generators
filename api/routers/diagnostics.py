from typing import Optional

from fastapi import APIRouter, HTTPException, Request

import deps
from models import Scene, ProjectStatus

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])


@router.post("/optimize-prompt")
@deps.limiter.limit("10/minute")
async def diagnostic_optimize(request: Request, body: dict):
    if not deps.ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await deps.ai_svc.analyze_brief(
        "diag-proj",
        body.get("concept", ""),
        body.get("length", "16"),
        body.get("orientation", "16:9"),
    )


@router.post("/generate-image")
@deps.limiter.limit("10/minute")
async def diagnostic_image(request: Request, body: dict):
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
@deps.limiter.limit("10/minute")
async def diagnostic_video(request: Request, body: dict):
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


@router.get("/operations/{name:path}")
async def check_operation_status(
    name: str,
    production_id: Optional[str] = None,
    scene_id: Optional[str] = None,
):
    if not deps.video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    status = await deps.video_svc.get_video_generation_status(name)

    if status.get("status") == "completed" and status.get("video_uri"):
        # Sign the URL before returning
        status["signed_url"] = deps.storage_svc.get_signed_url(status["video_uri"])

        # Persist video_url back to Firestore if scene context provided
        if production_id and scene_id and deps.firestore_svc:
            deps.firestore_svc.update_scene(
                production_id,
                scene_id,
                {
                    "status": "completed",
                    "video_url": status["video_uri"],
                },
            )

    elif (
        status.get("status") in ("failed", "error")
        and production_id
        and deps.firestore_svc
    ):
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

    return status

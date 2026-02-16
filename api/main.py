import os
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
from dotenv import load_dotenv

from models import Project, ProjectStatus, Scene, AIResponseWrapper, SystemResource
from firestore_service import FirestoreService
from ai_service import AIService
from video_service import VideoService
from transcoder_service import TranscoderService
from storage_service import StorageService


# Load environment variables
load_dotenv(dotenv_path="../.env.dev")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Veo Production API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global service instances (initialized on startup)
firestore_svc = None
ai_svc = None
video_svc = None
transcoder_svc = None
storage_svc = None


@app.on_event("startup")
async def startup_event():
    global firestore_svc, ai_svc, video_svc, transcoder_svc, storage_svc
    try:
        logger.info("Initializing services...")
        firestore_svc = FirestoreService()
        storage_svc = StorageService()
        ai_svc = AIService(storage_svc=storage_svc, firestore_svc=firestore_svc)
        video_svc = VideoService(storage_svc=storage_svc)
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        transcoder_svc = TranscoderService(project_id, location)
        logger.info("Services initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        # We don't raise here to allow the app to start and serve health checks
        # But endpoints relying on these will fail.


@app.get("/health")
async def health_check():
    status = "healthy"
    if not all([firestore_svc, ai_svc, video_svc, transcoder_svc, storage_svc]):
        status = "degraded"
    return {
        "status": status,
        "services_initialized": all(
            [firestore_svc, ai_svc, video_svc, transcoder_svc, storage_svc]
        ),
    }


# --- URL Signing Helpers ---


def _resolve_media_url(url: str) -> str:
    """Turn a GCS URI or expired signed URL into a fresh signed URL."""
    if not url or not storage_svc:
        return url or ""
    if url.startswith("gs://"):
        return storage_svc.get_signed_url(url)
    # Attempt to recover GCS URI from an expired signed URL
    gcs_uri = storage_svc.recover_gcs_uri(url)
    if gcs_uri:
        return storage_svc.get_signed_url(gcs_uri)
    return url


def _sign_production_urls(production: Project) -> dict:
    """Return a dict representation of the production with all media URLs re-signed."""
    data = production.dict()
    for scene in data.get("scenes", []):
        if scene.get("thumbnail_url"):
            scene["thumbnail_url"] = _resolve_media_url(scene["thumbnail_url"])
        if scene.get("video_url"):
            scene["video_url"] = _resolve_media_url(scene["video_url"])
    if data.get("final_video_url"):
        data["final_video_url"] = _resolve_media_url(data["final_video_url"])
    if data.get("reference_image_url"):
        data["reference_image_url"] = _resolve_media_url(data["reference_image_url"])
    return data


# --- Background Tasks ---


async def process_render_kickoff(production_id: str):
    """Fire off non-blocking video generation for all scenes that need it.

    Each scene gets its Veo operation started and the operation_name saved.
    The client polls each operation via the diagnostics endpoint, which
    persists results back to Firestore when complete.
    """
    if not firestore_svc or not video_svc:
        return
    production = firestore_svc.get_production(production_id)
    if not production:
        return

    try:
        for scene in production.scenes:
            if scene.video_url and scene.video_url.startswith("gs://"):
                logger.info(f"Scene {scene.id} already has video, skipping")
                if scene.status != "completed":
                    firestore_svc.update_scene(
                        production_id, scene.id, {"status": "completed"}
                    )
                continue

            firestore_svc.update_scene(
                production_id, scene.id, {"status": "generating"}
            )
            result = await video_svc.generate_scene_video(
                production_id, scene, blocking=False, project=production
            )
            if isinstance(result, dict):
                scene_updates = {}
                if result.get("operation_name"):
                    scene_updates["operation_name"] = result["operation_name"]
                if result.get("generated_prompt"):
                    scene_updates["generated_prompt"] = result["generated_prompt"]
                    scene_updates["video_prompt"] = result["generated_prompt"]
                if scene_updates:
                    firestore_svc.update_scene(production_id, scene.id, scene_updates)
    except Exception as e:
        logger.error(f"Render kickoff failed: {e}")
        firestore_svc.update_production(
            production_id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )


# --- Endpoints ---


@app.get("/api/v1/productions")
async def list_productions(archived: bool = False):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    productions = firestore_svc.get_productions(include_archived=archived)
    return [_sign_production_urls(p) for p in productions]


@app.post("/api/v1/productions", response_model=Project)
async def create_production(project: Project):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.create_production(project)
    return project


@app.get("/api/v1/productions/{id}")
async def get_production(id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    return _sign_production_urls(p)


@app.post("/api/v1/productions/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(id: str, request: dict = {}):
    if not firestore_svc or not ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)

    prompt_id = request.get("prompt_id")
    schema_id = request.get("schema_id")

    firestore_svc.update_production(id, {"status": ProjectStatus.ANALYZING})
    result = await ai_svc.analyze_brief(
        id,
        p.base_concept,
        p.video_length,
        p.orientation,
        prompt_id=prompt_id,
        schema_id=schema_id,
        project_type=p.type,
    )

    result_data = (
        result.data
    )  # now a dict with scenes, global_style, continuity, analysis_prompt

    # Resolve names/versions for badges if IDs were provided
    prompt_info = None
    if prompt_id:
        res = firestore_svc.get_resource(prompt_id)
        if res:
            prompt_info = {"id": res.id, "name": res.name, "version": res.version}

    schema_info = None
    if schema_id:
        res = firestore_svc.get_resource(schema_id)
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

    firestore_svc.update_production(id, updates)
    return result


@app.post(
    "/api/v1/productions/{id}/scenes/{scene_id}/frame", response_model=AIResponseWrapper
)
async def generate_scene_frame(id: str, scene_id: str):
    if not firestore_svc or not ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    result = await ai_svc.generate_frame(
        id, scene, production.orientation, project=production
    )
    gcs_uri = result.data["image_url"]
    scene_updates = {"thumbnail_url": gcs_uri}
    if result.data.get("generated_prompt"):
        scene_updates["generated_prompt"] = result.data["generated_prompt"]
        scene_updates["image_prompt"] = result.data["generated_prompt"]
    firestore_svc.update_scene(id, scene_id, scene_updates)
    # Return signed URL for immediate display
    result.data["image_url"] = _resolve_media_url(gcs_uri)
    return result


@app.post("/api/v1/productions/{id}/scenes/{scene_id}/video")
async def generate_scene_video(id: str, scene_id: str):
    if not firestore_svc or not video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    firestore_svc.update_scene(id, scene_id, {"status": "generating"})
    result = await video_svc.generate_scene_video(
        id, scene, blocking=False, project=production
    )

    if isinstance(result, dict) and "operation_name" in result:
        if result.get("generated_prompt"):
            firestore_svc.update_scene(
                id,
                scene_id,
                {
                    "generated_prompt": result["generated_prompt"],
                    "video_prompt": result["generated_prompt"],
                },
            )
        return {"operation_name": result["operation_name"], "status": "processing"}

    # Blocking result
    if isinstance(result, dict) and result.get("video_uri"):
        scene_updates = {
            "status": "completed",
            "video_url": result["video_uri"],
        }
        if result.get("generated_prompt"):
            scene_updates["generated_prompt"] = result["generated_prompt"]
            scene_updates["video_prompt"] = result["generated_prompt"]
        firestore_svc.update_scene(id, scene_id, scene_updates)
        signed_url = (
            storage_svc.get_signed_url(result["video_uri"]) if storage_svc else None
        )
        return {
            "status": "completed",
            "video_uri": result["video_uri"],
            "signed_url": signed_url,
        }

    firestore_svc.update_scene(id, scene_id, {"status": "failed"})
    return {"status": "failed"}


@app.post("/api/v1/productions/{id}/archive")
async def archive_production(id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    firestore_svc.update_production(id, {"archived": True})
    return {"status": "archived"}


@app.post("/api/v1/productions/{id}/unarchive")
async def unarchive_production(id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p:
        raise HTTPException(status_code=404)
    firestore_svc.update_production(id, {"archived": False})
    return {"status": "unarchived"}


@app.post("/api/v1/productions/{id}/render")
async def start_render(id: str, background_tasks: BackgroundTasks):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_render_kickoff, id)
    return {"status": "started"}


@app.post("/api/v1/productions/{id}/stitch")
async def stitch_production(id: str):
    """Stitch all completed scene videos into a final video.

    Called by the client once all scenes have video_url populated.
    """
    if not firestore_svc or not transcoder_svc or not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene_uris = []
    for scene in production.scenes:
        if not scene.video_url or not scene.video_url.startswith("gs://"):
            raise HTTPException(
                status_code=400,
                detail=f"Scene {scene.id} does not have a video yet",
            )
        scene_uris.append(scene.video_url)

    firestore_svc.update_production(id, {"status": ProjectStatus.STITCHING})
    try:
        final_uri = transcoder_svc.stitch_from_uris(
            id, scene_uris, orientation=production.orientation
        )
        firestore_svc.update_production(
            id,
            {"status": ProjectStatus.COMPLETED, "final_video_url": final_uri},
        )
        signed_url = storage_svc.get_signed_url(final_uri)
        return {"status": "completed", "final_video_url": signed_url}
    except Exception as e:
        logger.error(f"Stitching failed: {e}")
        firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    if not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = storage_svc.upload_file(content, destination, file.content_type)
    return {"gcs_uri": gcs_uri, "signed_url": storage_svc.get_signed_url(gcs_uri)}


# --- System Resource Endpoints ---


@app.get("/api/v1/system/resources", response_model=List[SystemResource])
async def list_system_resources(
    type: Optional[str] = None, category: Optional[str] = None
):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return firestore_svc.list_resources(resource_type=type, category=category)


@app.post("/api/v1/system/resources", response_model=SystemResource)
async def create_system_resource(resource: SystemResource):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.create_resource(resource)
    return resource


@app.post("/api/v1/system/resources/{id}/activate")
async def activate_system_resource(id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.set_resource_active(id)
    return {"status": "success"}


@app.get("/api/v1/system/default-schema")
async def get_default_schema():
    from ai_service import _load_default_schema

    return _load_default_schema()


# --- Diagnostic Endpoints ---


@app.post("/api/v1/diagnostics/optimize-prompt")
async def diagnostic_optimize(request: dict):
    if not ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return await ai_svc.analyze_brief(
        "diag-proj",
        request.get("concept", ""),
        request.get("length", "16"),
        request.get("orientation", "16:9"),
    )


@app.post("/api/v1/diagnostics/generate-image")
async def diagnostic_image(request: dict):
    if not ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    scene = Scene(
        visual_description=request.get("prompt", ""),
        timestamp_start="0",
        timestamp_end="8",
    )
    return await ai_svc.generate_frame(
        "diag-proj", scene, request.get("orientation", "16:9")
    )


@app.post("/api/v1/diagnostics/generate-video")
async def diagnostic_video(request: dict):
    if not video_svc or not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    scene = Scene(
        visual_description=request.get("prompt", ""),
        timestamp_start="0",
        timestamp_end="8",
    )

    result = await video_svc.generate_scene_video("diag-proj", scene, blocking=False)

    if isinstance(result, dict) and "operation_name" in result:
        return result

    return {
        "video_uri": result,
        "signed_url": storage_svc.get_signed_url(result) if result else None,
    }


@app.get("/api/v1/diagnostics/operations/{name:path}")
async def check_operation_status(
    name: str,
    production_id: Optional[str] = None,
    scene_id: Optional[str] = None,
):
    if not video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    status = await video_svc.get_video_generation_status(name)

    if status.get("status") == "completed" and status.get("video_uri"):
        # Sign the URL before returning
        status["signed_url"] = storage_svc.get_signed_url(status["video_uri"])

        # Persist video_url back to Firestore if scene context provided
        if production_id and scene_id and firestore_svc:
            firestore_svc.update_scene(
                production_id,
                scene_id,
                {
                    "status": "completed",
                    "video_url": status["video_uri"],
                },
            )

    return status


# --- SPA Serving ---
if os.path.exists("static"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join("static", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    import uuid

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

import os
import uuid
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Optional
from dotenv import load_dotenv

from models import (
    Project,
    ProjectStatus,
    Scene,
    AIResponseWrapper,
    SystemResource,
    KeyMomentsRecord,
    ThumbnailRecord,
    ThumbnailScreenshot,
    UploadRecord,
    CompressedVariant,
    UploadInitRequest,
    UploadCompleteRequest,
)
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


def _sign_production_urls(production: Project, thumbnails_only: bool = False) -> dict:
    """Return a dict with media URLs resolved from cache. Re-signs only near expiry.

    When thumbnails_only=True, only sign scene thumbnails (for list views).
    Persists updated signed URL cache back to Firestore when any URL was refreshed.
    """
    if not storage_svc:
        return production.dict()

    data = production.dict()
    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri:
            return ""
        # Recover GCS URI from expired signed URLs
        if not gcs_uri.startswith("gs://"):
            recovered = storage_svc.recover_gcs_uri(gcs_uri)
            if recovered:
                gcs_uri = recovered
            else:
                return gcs_uri
        url, changed = storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    for scene in data.get("scenes", []):
        if scene.get("thumbnail_url"):
            scene["thumbnail_url"] = _resolve(scene["thumbnail_url"])
        if not thumbnails_only and scene.get("video_url"):
            scene["video_url"] = _resolve(scene["video_url"])
    if not thumbnails_only:
        if data.get("final_video_url"):
            data["final_video_url"] = _resolve(data["final_video_url"])
        if data.get("reference_image_url"):
            data["reference_image_url"] = _resolve(data["reference_image_url"])

    if dirty and firestore_svc:
        firestore_svc.update_production(production.id, {"signed_urls": cache})

    # Don't leak the cache to the client
    data.pop("signed_urls", None)
    return data


def _accumulate_cost(production_id: str, cost_usd: float):
    """Add cost to the production's total_usage."""
    production = firestore_svc.get_production(production_id)
    if not production:
        return
    current = production.total_usage.cost_usd if production.total_usage else 0.0
    firestore_svc.update_production(
        production_id, {"total_usage": {"cost_usd": current + cost_usd}}
    )


# --- Prompt Building Helpers ---


def _parse_timestamp(ts: str) -> float:
    """Parse '00:05' or '5' to seconds."""
    if ":" in ts:
        parts = ts.split(":")
        return int(parts[0]) * 60 + float(parts[1])
    return float(ts)


def _build_prompt_data(scene: Scene, project: Project) -> dict:
    """Build structured prompt data for a scene including all production context."""
    SUPPORTED_DURATIONS = [4, 6, 8]
    try:
        start = _parse_timestamp(scene.timestamp_start)
        end = _parse_timestamp(scene.timestamp_end)
        raw = int(end - start)
        duration = min(SUPPORTED_DURATIONS, key=lambda d: abs(d - raw))
    except (ValueError, IndexError):
        duration = 8

    data = {
        "visual_description": scene.visual_description,
        "metadata": scene.metadata.dict() if scene.metadata else {},
        "global_style": project.global_style.dict() if project.global_style else None,
        "continuity": project.continuity.dict() if project.continuity else None,
        "duration": duration,
        "narration": scene.narration,
        "narration_enabled": scene.narration_enabled,
        "music_description": scene.music_description,
        "music_enabled": scene.music_enabled,
    }
    data["image_prompt"] = _build_flat_image_prompt(data)
    data["video_prompt"] = _build_flat_video_prompt(data)
    return data


def _build_flat_image_prompt(data: dict) -> str:
    """Build a flat text prompt for image generation from structured data."""
    parts = []
    gs = data.get("global_style")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
        )
    cont = data.get("continuity")
    if cont and cont.get("characters"):
        char_descs = [
            f"{c['id']}: {c['description']}, wearing {c.get('wardrobe', '')}"
            for c in cont["characters"]
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if cont and cont.get("setting_notes"):
        parts.append(f"Setting: {cont['setting_notes']}.")
    parts.append(data.get("visual_description", ""))
    return " ".join(parts)


def _build_flat_video_prompt(data: dict) -> str:
    """Build a flat text prompt for video generation from structured data."""
    parts = []
    duration = data.get("duration", 8)
    parts.append(f"{duration}-second video clip.")
    md = data.get("metadata", {})
    if md.get("camera_angle"):
        parts.append(f"Camera angle: {md['camera_angle']}.")
    if md.get("camera_movement"):
        parts.append(f"Camera movement: {md['camera_movement']}.")
    if md.get("cinematic_style"):
        parts.append(f"Cinematic style: {md['cinematic_style']}.")
    gs = data.get("global_style")
    pace = md.get("pace") or (gs.get("pace") if gs else None)
    if pace:
        parts.append(f"Pace: {pace}.")
    if gs:
        parts.append(
            f"Style: {gs.get('look', '')}. Mood: {gs.get('mood', '')}. "
            f"Colors: {gs.get('color_grading', '')}. Lighting: {gs.get('lighting_style', '')}."
        )
    cont = data.get("continuity")
    if cont and cont.get("characters"):
        char_descs = [
            f"{c['id']}: {c['description']}, wearing {c.get('wardrobe', '')}"
            for c in cont["characters"]
        ]
        parts.append(f"Characters: {'; '.join(char_descs)}.")
    if cont and cont.get("setting_notes"):
        parts.append(f"Setting: {cont['setting_notes']}.")
    parts.append(data.get("visual_description", ""))

    # Narration (only if enabled)
    if data.get("narration_enabled"):
        narration = data.get("narration")
        if narration:
            parts.append(f'Voice-over narration: "{narration}"')

    # Music (only if enabled; scene-level falls back to global soundtrack_style)
    if data.get("music_enabled"):
        music = data.get("music_description")
        if not music:
            gs = data.get("global_style")
            if gs and gs.get("soundtrack_style"):
                music = gs["soundtrack_style"]
        if music:
            parts.append(f"Background music: {music}.")

    return " ".join(parts)


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
    return [_sign_production_urls(p, thumbnails_only=True) for p in productions]


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


@app.post("/api/v1/productions/{id}/scenes/{scene_id}/build-prompt")
async def build_scene_prompt(id: str, scene_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)
    return _build_prompt_data(scene, production)


@app.patch("/api/v1/productions/{id}/scenes/{scene_id}")
async def update_scene(id: str, scene_id: str, updates: dict):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    ALLOWED = {
        "visual_description",
        "narration",
        "narration_enabled",
        "music_description",
        "music_enabled",
    }
    filtered = {k: v for k, v in updates.items() if k in ALLOWED}
    if filtered:
        firestore_svc.update_scene(id, scene_id, filtered)
    return {"ok": True}


@app.post(
    "/api/v1/productions/{id}/scenes/{scene_id}/frame",
    response_model=AIResponseWrapper,
)
async def generate_scene_frame(id: str, scene_id: str, request: dict = {}):
    if not firestore_svc or not ai_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    prompt_override = None
    prompt_data = request.get("prompt_data") if request else None
    if prompt_data:
        prompt_override = _build_flat_image_prompt(prompt_data)
        new_desc = prompt_data.get("visual_description")
        if new_desc and new_desc != scene.visual_description:
            firestore_svc.update_scene(id, scene_id, {"visual_description": new_desc})

    try:
        result = await ai_svc.generate_frame(
            id,
            scene,
            production.orientation,
            project=production,
            prompt_override=prompt_override,
        )
    except Exception as e:
        logger.error(f"Frame generation failed for scene {scene_id}: {e}")
        error_msg = f"Image generation failed for scene {scene_id}: {e}"
        firestore_svc.update_scene(
            id, scene_id, {"status": "failed", "error_message": str(e)}
        )
        firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
        )
        raise HTTPException(status_code=500, detail=error_msg)

    gcs_uri = result.data["image_url"]
    scene_updates = {"thumbnail_url": gcs_uri}
    if result.data.get("generated_prompt"):
        scene_updates["generated_prompt"] = result.data["generated_prompt"]
        scene_updates["image_prompt"] = result.data["generated_prompt"]
    firestore_svc.update_scene(id, scene_id, scene_updates)
    _accumulate_cost(id, result.usage.cost_usd)
    # Return signed URL for immediate display
    result.data["image_url"] = storage_svc.get_signed_url(gcs_uri)
    return result


@app.post("/api/v1/productions/{id}/scenes/{scene_id}/video")
async def generate_scene_video(id: str, scene_id: str, request: dict = {}):
    if not firestore_svc or not video_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene:
        raise HTTPException(status_code=404)

    prompt_override = None
    prompt_data = request.get("prompt_data") if request else None
    if prompt_data:
        prompt_override = _build_flat_video_prompt(prompt_data)
        new_desc = prompt_data.get("visual_description")
        if new_desc and new_desc != scene.visual_description:
            firestore_svc.update_scene(id, scene_id, {"visual_description": new_desc})

    firestore_svc.update_scene(id, scene_id, {"status": "generating"})
    result = await video_svc.generate_scene_video(
        id, scene, blocking=False, project=production, prompt_override=prompt_override
    )

    # Calculate Veo cost: $0.40/second
    try:
        veo_start = _parse_timestamp(scene.timestamp_start)
        veo_end = _parse_timestamp(scene.timestamp_end)
        veo_duration = max(4, min(8, int(veo_end - veo_start)))
    except (ValueError, IndexError):
        veo_duration = 8
    veo_cost = veo_duration * 0.40
    _accumulate_cost(id, veo_cost)

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

    error_msg = f"Video generation failed for scene {scene_id}"
    firestore_svc.update_scene(
        id, scene_id, {"status": "failed", "error_message": error_msg}
    )
    firestore_svc.update_production(
        id, {"status": ProjectStatus.FAILED, "error_message": error_msg}
    )
    return {"status": "failed", "error_message": error_msg}


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
        job_name, final_uri = transcoder_svc.stitch_from_uris(
            id, scene_uris, orientation=production.orientation
        )
        firestore_svc.update_production(
            id,
            {
                "stitch_job_name": job_name,
                "final_video_url": final_uri,
            },
        )
        return {"status": "stitching", "job_name": job_name}
    except Exception as e:
        logger.error(f"Stitching failed: {e}")
        firestore_svc.update_production(
            id, {"status": ProjectStatus.FAILED, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/productions/{id}/stitch-status")
async def get_stitch_status(id: str):
    """Check the status of a running stitch (Transcoder) job."""
    if not firestore_svc or not transcoder_svc or not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production:
        raise HTTPException(status_code=404)

    if not production.stitch_job_name:
        return {"status": str(production.status.value)}

    job_state = transcoder_svc.get_job_status(production.stitch_job_name)

    if job_state == "SUCCEEDED":
        firestore_svc.update_production(id, {"status": ProjectStatus.COMPLETED})
        signed_url = (
            storage_svc.get_signed_url(production.final_video_url)
            if production.final_video_url
            else None
        )
        return {
            "status": "completed",
            "final_video_url": signed_url,
        }
    elif job_state in ("FAILED", "UNKNOWN"):
        firestore_svc.update_production(
            id,
            {
                "status": ProjectStatus.FAILED,
                "error_message": f"Transcoder job {job_state}",
            },
        )
        return {"status": "failed", "error": f"Transcoder job {job_state}"}
    else:
        return {"status": "stitching", "job_state": job_state}


@app.post("/api/v1/assets/upload/init")
async def upload_init(request: UploadInitRequest):
    """Generate a signed PUT URL for direct-to-GCS upload."""
    if not storage_svc or not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")

    mime = request.content_type or ""
    if mime.startswith("video/"):
        file_type = "video"
    elif mime.startswith("image/"):
        file_type = "image"
    else:
        file_type = "other"

    destination = f"uploads/{uuid.uuid4()}-{request.filename}"
    signed = storage_svc.generate_upload_signed_url(destination, request.content_type)

    record = UploadRecord(
        filename=request.filename,
        mime_type=request.content_type,
        file_type=file_type,
        gcs_uri=signed["gcs_uri"],
        file_size_bytes=request.file_size_bytes,
        status="pending",
    )
    firestore_svc.create_upload_record(record)

    return {
        "record_id": record.id,
        "upload_url": signed["upload_url"],
        "gcs_uri": signed["gcs_uri"],
        "content_type": request.content_type,
        "expires_at": signed["expires_at"],
    }


@app.post("/api/v1/assets/upload/complete")
async def upload_complete(request: UploadCompleteRequest):
    """Verify a direct upload landed in GCS and finalize the record."""
    if not storage_svc or not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")

    record = firestore_svc.get_upload_record(request.record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload record not found")

    if not storage_svc.blob_exists(record.gcs_uri):
        firestore_svc.update_upload_record(request.record_id, {"status": "failed"})
        raise HTTPException(status_code=400, detail="File not found in GCS")

    actual_size = storage_svc.get_file_size(record.gcs_uri)
    firestore_svc.update_upload_record(
        request.record_id,
        {"status": "completed", "file_size_bytes": actual_size},
    )

    signed_url = storage_svc.get_signed_url(record.gcs_uri)
    return {
        "id": record.id,
        "gcs_uri": record.gcs_uri,
        "signed_url": signed_url,
        "file_type": record.file_type,
    }


@app.post("/api/v1/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    if not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = storage_svc.upload_file(content, destination, file.content_type)
    signed_url = storage_svc.get_signed_url(gcs_uri)

    # Derive file_type from MIME prefix
    mime = file.content_type or ""
    if mime.startswith("video/"):
        file_type = "video"
    elif mime.startswith("image/"):
        file_type = "image"
    else:
        file_type = "other"

    # Persist to Firestore
    record = UploadRecord(
        filename=file.filename or "unknown",
        mime_type=mime,
        file_type=file_type,
        gcs_uri=gcs_uri,
        file_size_bytes=len(content),
    )
    if firestore_svc:
        firestore_svc.create_upload_record(record)

    return {
        "id": record.id,
        "gcs_uri": gcs_uri,
        "signed_url": signed_url,
        "file_type": file_type,
    }


# --- Upload Management Endpoints ---


def _sign_upload_urls(record: UploadRecord) -> dict:
    """Return record dict with signed URLs for the file and compressed variants."""
    data = record.dict()
    if not storage_svc:
        return data

    # Backfill file size if missing (e.g. compressed children created before fix)
    if record.file_size_bytes == 0 and record.gcs_uri:
        size = storage_svc.get_file_size(record.gcs_uri)
        if size > 0:
            data["file_size_bytes"] = size
            if firestore_svc:
                firestore_svc.update_upload_record(record.id, {"file_size_bytes": size})

    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri
        url, changed = storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    # Sign main file
    data["signed_url"] = _resolve(record.gcs_uri)

    # Sign compressed variants
    for variant in data.get("compressed_variants", []):
        if variant.get("gcs_uri") and variant.get("status") == "succeeded":
            variant["signed_url"] = _resolve(variant["gcs_uri"])

    if dirty and firestore_svc:
        firestore_svc.update_upload_record(record.id, {"signed_urls": cache})

    data.pop("signed_urls", None)
    return data


@app.get("/api/v1/uploads")
async def list_uploads(archived: bool = False, file_type: Optional[str] = None):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    records = firestore_svc.get_upload_records(
        include_archived=archived, file_type=file_type
    )
    return [_sign_upload_urls(r) for r in records]


@app.get("/api/v1/uploads/{record_id}")
async def get_upload(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    return _sign_upload_urls(record)


@app.post("/api/v1/uploads/{record_id}/compress")
async def compress_upload(record_id: str, request: dict):
    if not firestore_svc or not transcoder_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    if record.file_type != "video":
        raise HTTPException(
            status_code=400, detail="Only video files can be compressed"
        )

    resolution = request.get("resolution")
    if resolution not in ("480p", "720p"):
        raise HTTPException(
            status_code=400, detail="Resolution must be '480p' or '720p'"
        )

    # Check if variant already exists and is processing/succeeded
    for v in record.compressed_variants:
        if v.resolution == resolution and v.status in ("processing", "succeeded"):
            raise HTTPException(
                status_code=400,
                detail=f"{resolution} variant already {v.status}",
            )

    try:
        job_name, output_uri = transcoder_svc.compress_video(
            record_id, record.gcs_uri, resolution
        )
        new_variant = CompressedVariant(
            resolution=resolution,
            gcs_uri=output_uri,
            job_name=job_name,
            status="processing",
        )
        # Remove any failed variant with same resolution, then append new one
        updated_variants = [
            v.dict() for v in record.compressed_variants if v.resolution != resolution
        ]
        updated_variants.append(new_variant.dict())
        firestore_svc.update_upload_record(
            record_id, {"compressed_variants": updated_variants}
        )
        return {"status": "processing", "job_name": job_name, "resolution": resolution}
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/uploads/{record_id}/compress-status")
async def get_compress_status(record_id: str):
    if not firestore_svc or not transcoder_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")

    updated = False
    variants = [v.dict() for v in record.compressed_variants]
    for v in variants:
        if v["status"] == "processing" and v["job_name"]:
            job_state = transcoder_svc.get_job_status(v["job_name"])
            if job_state == "SUCCEEDED":
                v["status"] = "succeeded"
                updated = True
                # Create a child UploadRecord if not already created
                if not v.get("child_upload_id"):
                    resolution = v["resolution"]
                    base, ext = os.path.splitext(record.filename)
                    child_filename = f"{base}-{resolution}{ext}"
                    child_size = (
                        storage_svc.get_file_size(v["gcs_uri"]) if storage_svc else 0
                    )
                    child_record = UploadRecord(
                        filename=child_filename,
                        mime_type=record.mime_type,
                        file_type="video",
                        gcs_uri=v["gcs_uri"],
                        file_size_bytes=child_size,
                        parent_upload_id=record_id,
                        resolution_label=resolution,
                    )
                    firestore_svc.create_upload_record(child_record)
                    v["child_upload_id"] = child_record.id
            elif job_state in ("FAILED", "UNKNOWN"):
                v["status"] = "failed"
                updated = True

    if updated:
        firestore_svc.update_upload_record(record_id, {"compressed_variants": variants})

    # Sign URLs for succeeded variants
    result_variants = []
    for v in variants:
        if v["status"] == "succeeded" and v["gcs_uri"] and storage_svc:
            v["signed_url"] = storage_svc.get_signed_url(v["gcs_uri"])
        result_variants.append(v)

    return {"variants": result_variants}


@app.post("/api/v1/uploads/{record_id}/archive")
async def archive_upload(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    firestore_svc.update_upload_record(record_id, {"archived": True})
    return {"status": "archived"}


@app.delete("/api/v1/uploads/{record_id}")
async def delete_upload(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    firestore_svc.delete_upload_record(record_id)
    return {"status": "deleted"}


# --- Key Moments Endpoints ---


def _sign_key_moments_url(record: KeyMomentsRecord) -> dict:
    """Return record dict with a signed video URL."""
    data = record.dict()
    if not storage_svc or not record.video_gcs_uri:
        return data
    cache = data.get("signed_urls") or {}
    url, changed = storage_svc.resolve_cached_url(record.video_gcs_uri, cache)
    data["video_signed_url"] = url
    if changed and firestore_svc:
        firestore_svc.key_moments_collection.document(record.id).update(
            {"signed_urls": cache}
        )
    data.pop("signed_urls", None)
    return data


@app.get("/api/v1/key-moments")
async def list_key_moments(archived: bool = False):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    records = firestore_svc.get_key_moments_analyses(include_archived=archived)
    return [_sign_key_moments_url(r) for r in records]


@app.get("/api/v1/key-moments/sources/productions")
async def list_production_sources():
    """List completed productions with signed final video URLs."""
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    productions = firestore_svc.get_productions()
    completed = [
        p
        for p in productions
        if p.status == ProjectStatus.COMPLETED and p.final_video_url
    ]
    results = []
    for p in completed:
        signed_url = ""
        if storage_svc and p.final_video_url:
            if p.final_video_url.startswith("gs://"):
                signed_url = storage_svc.get_signed_url(p.final_video_url)
            else:
                signed_url = p.final_video_url
        results.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "final_video_url": p.final_video_url,
                "video_signed_url": signed_url,
                "createdAt": p.createdAt.isoformat() if p.createdAt else None,
            }
        )
    return results


@app.get("/api/v1/key-moments/{record_id}")
async def get_key_moments_analysis(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return _sign_key_moments_url(record)


@app.post("/api/v1/key-moments/analyze")
async def analyze_key_moments(request: dict):
    if not ai_svc or not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    gcs_uri = request.get("gcs_uri")
    prompt_id = request.get("prompt_id")
    if not gcs_uri or not prompt_id:
        raise HTTPException(
            status_code=400, detail="gcs_uri and prompt_id are required"
        )
    mime_type = request.get("mime_type", "video/mp4")
    schema_id = request.get("schema_id")
    video_filename = request.get("video_filename", "")
    video_source = request.get("video_source", "upload")
    production_id = request.get("production_id")
    try:
        result = await ai_svc.analyze_video_key_moments(
            gcs_uri=gcs_uri,
            mime_type=mime_type,
            prompt_id=prompt_id,
            schema_id=schema_id,
        )
        # Persist to Firestore
        analysis_data = result.data if hasattr(result, "data") else result.get("data")
        record = KeyMomentsRecord(
            video_gcs_uri=gcs_uri,
            video_filename=video_filename,
            video_source=video_source,
            production_id=production_id,
            mime_type=mime_type,
            prompt_id=prompt_id,
            video_summary=analysis_data.get("video_summary") if analysis_data else None,
            key_moments=[
                m
                for m in (analysis_data.get("key_moments", []) if analysis_data else [])
            ],
            moment_count=len(
                analysis_data.get("key_moments", []) if analysis_data else []
            ),
            usage=result.usage if hasattr(result, "usage") else result.get("usage", {}),
        )
        firestore_svc.create_key_moments_analysis(record)
        return {"id": record.id, "data": analysis_data, "usage": record.usage.dict()}
    except Exception as e:
        logger.error(f"Key moments analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/key-moments/{record_id}/archive")
async def archive_key_moments_analysis(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    firestore_svc.key_moments_collection.document(record_id).update({"archived": True})
    return {"status": "archived"}


@app.delete("/api/v1/key-moments/{record_id}")
async def delete_key_moments_analysis(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_key_moments_analysis(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
    firestore_svc.delete_key_moments_analysis(record_id)
    return {"status": "deleted"}


# --- Thumbnail Endpoints ---


def _sign_thumbnail_urls(record: ThumbnailRecord) -> dict:
    """Return record dict with signed URLs for video, screenshots, and thumbnail."""
    data = record.dict()
    if not storage_svc:
        return data
    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri:
            return ""
        if not gcs_uri.startswith("gs://"):
            return gcs_uri
        url, changed = storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    # Sign video URL
    if record.video_gcs_uri:
        data["video_signed_url"] = _resolve(record.video_gcs_uri)

    # Sign screenshot URLs
    for screenshot in data.get("screenshots", []):
        if screenshot.get("gcs_uri"):
            screenshot["signed_url"] = _resolve(screenshot["gcs_uri"])

    # Sign thumbnail URL
    if record.thumbnail_gcs_uri:
        data["thumbnail_signed_url"] = _resolve(record.thumbnail_gcs_uri)

    if dirty and firestore_svc:
        firestore_svc.update_thumbnail_record(record.id, {"signed_urls": cache})

    data.pop("signed_urls", None)
    return data


@app.get("/api/v1/thumbnails")
async def list_thumbnails(archived: bool = False):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    records = firestore_svc.get_thumbnail_records(include_archived=archived)
    return [_sign_thumbnail_urls(r) for r in records]


@app.get("/api/v1/thumbnails/sources/productions")
async def list_thumbnail_production_sources():
    """List completed productions with signed final video URLs."""
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    productions = firestore_svc.get_productions()
    completed = [
        p
        for p in productions
        if p.status == ProjectStatus.COMPLETED and p.final_video_url
    ]
    results = []
    for p in completed:
        signed_url = ""
        if storage_svc and p.final_video_url:
            if p.final_video_url.startswith("gs://"):
                signed_url = storage_svc.get_signed_url(p.final_video_url)
            else:
                signed_url = p.final_video_url
        results.append(
            {
                "id": p.id,
                "name": p.name,
                "type": p.type,
                "final_video_url": p.final_video_url,
                "video_signed_url": signed_url,
                "createdAt": p.createdAt.isoformat() if p.createdAt else None,
            }
        )
    return results


@app.get("/api/v1/thumbnails/{record_id}")
async def get_thumbnail_record(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_thumbnail_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Thumbnail record not found")
    return _sign_thumbnail_urls(record)


@app.post("/api/v1/thumbnails/analyze")
async def analyze_video_for_thumbnails(request: dict):
    if not ai_svc or not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    gcs_uri = request.get("gcs_uri")
    prompt_id = request.get("prompt_id")
    if not gcs_uri or not prompt_id:
        raise HTTPException(
            status_code=400, detail="gcs_uri and prompt_id are required"
        )
    mime_type = request.get("mime_type", "video/mp4")
    video_filename = request.get("video_filename", "")
    video_source = request.get("video_source", "upload")
    production_id = request.get("production_id")
    try:
        result = await ai_svc.analyze_video_for_thumbnails(
            gcs_uri=gcs_uri,
            mime_type=mime_type,
            prompt_id=prompt_id,
        )
        analysis_data = result.data if hasattr(result, "data") else result.get("data")
        moments = analysis_data.get("key_moments", []) if analysis_data else []
        screenshots = [
            ThumbnailScreenshot(
                timestamp=f"{m.get('timestamp_start', '0:00')}-{m.get('timestamp_end', '0:00')}",
                title=m.get("title", ""),
                description=m.get("description", ""),
                visual_characteristics=m.get("visual_characteristics", ""),
                category=m.get("category"),
                tags=m.get("tags", []),
            )
            for m in moments
        ]
        record = ThumbnailRecord(
            video_gcs_uri=gcs_uri,
            video_filename=video_filename,
            video_source=video_source,
            production_id=production_id,
            mime_type=mime_type,
            analysis_prompt_id=prompt_id,
            video_summary=analysis_data.get("video_summary") if analysis_data else None,
            screenshots=screenshots,
            status="screenshots_ready",
            usage=result.usage if hasattr(result, "usage") else result.get("usage", {}),
        )
        firestore_svc.create_thumbnail_record(record)
        return {"id": record.id, "data": analysis_data, "usage": record.usage.dict()}
    except Exception as e:
        logger.error(f"Thumbnail analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/thumbnails/{record_id}/screenshots")
async def save_thumbnail_screenshots(record_id: str, request: dict):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_thumbnail_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Thumbnail record not found")
    incoming = request.get("screenshots", [])
    updated_screenshots = [s.dict() for s in record.screenshots]
    for item in incoming:
        idx = item.get("index")
        gcs_uri = item.get("gcs_uri")
        if idx is not None and 0 <= idx < len(updated_screenshots) and gcs_uri:
            updated_screenshots[idx]["gcs_uri"] = gcs_uri
    firestore_svc.update_thumbnail_record(
        record_id,
        {"screenshots": updated_screenshots, "status": "screenshots_ready"},
    )
    return {"status": "screenshots_saved"}


@app.post("/api/v1/thumbnails/{record_id}/collage")
async def generate_thumbnail_collage(record_id: str, request: dict):
    if not ai_svc or not firestore_svc or not storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_thumbnail_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Thumbnail record not found")
    prompt_id = request.get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=400, detail="prompt_id is required")
    screenshot_uris = [s.gcs_uri for s in record.screenshots if s.gcs_uri]
    if not screenshot_uris:
        raise HTTPException(
            status_code=400, detail="No screenshots with GCS URIs found"
        )
    firestore_svc.update_thumbnail_record(
        record_id, {"status": "generating", "collage_prompt_id": prompt_id}
    )
    try:
        result = await ai_svc.generate_thumbnail_collage(
            screenshot_uris=screenshot_uris,
            prompt_id=prompt_id,
        )
        thumbnail_gcs_uri = result.data.get("thumbnail_url")
        signed_url = (
            storage_svc.get_signed_url(thumbnail_gcs_uri) if thumbnail_gcs_uri else None
        )
        firestore_svc.update_thumbnail_record(
            record_id,
            {
                "thumbnail_gcs_uri": thumbnail_gcs_uri,
                "status": "completed",
            },
        )
        return {
            "thumbnail_gcs_uri": thumbnail_gcs_uri,
            "thumbnail_signed_url": signed_url,
        }
    except Exception as e:
        logger.error(f"Collage generation failed: {e}")
        firestore_svc.update_thumbnail_record(
            record_id, {"status": "screenshots_ready"}
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/thumbnails/{record_id}/archive")
async def archive_thumbnail(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_thumbnail_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Thumbnail record not found")
    firestore_svc.update_thumbnail_record(record_id, {"archived": True})
    return {"status": "archived"}


@app.delete("/api/v1/thumbnails/{record_id}")
async def delete_thumbnail(record_id: str):
    if not firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = firestore_svc.get_thumbnail_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Thumbnail record not found")
    firestore_svc.delete_thumbnail_record(record_id)
    return {"status": "deleted"}


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

    elif (
        status.get("status") in ("failed", "error") and production_id and firestore_svc
    ):
        error_msg = (
            status.get("error") or status.get("message") or "Video generation failed"
        )
        if scene_id:
            firestore_svc.update_scene(
                production_id,
                scene_id,
                {"status": "failed", "error_message": str(error_msg)},
            )
        firestore_svc.update_production(
            production_id,
            {
                "status": ProjectStatus.FAILED,
                "error_message": f"Video generation failed for scene {scene_id or 'unknown'}: {error_msg}",
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

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

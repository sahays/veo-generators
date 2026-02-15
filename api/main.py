import os
import logging
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from typing import List
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(dotenv_path="../.env.dev")

from models import (
    Project, ProjectStatus, Scene, AIResponseWrapper
)
from firestore_service import FirestoreService
from ai_service import AIService
from storage_service import StorageService

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
storage_svc = None

@app.on_event("startup")
async def startup_event():
    global firestore_svc, ai_svc, storage_svc
    try:
        logger.info("Initializing services...")
        firestore_svc = FirestoreService()
        ai_svc = AIService()
        storage_svc = StorageService()
        logger.info("Services initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        # We don't raise here to allow the app to start and serve health checks
        # But endpoints relying on these will fail.

@app.get("/health")
async def health_check():
    status = "healthy"
    if not all([firestore_svc, ai_svc, storage_svc]):
        status = "degraded"
    return {"status": status, "services_initialized": all([firestore_svc, ai_svc, storage_svc])}

# --- Background Tasks ---

async def process_sequential_generation(production_id: str):
    if not firestore_svc or not ai_svc: return
    production = firestore_svc.get_production(production_id)
    if not production: return

    try:
        scene_uris = []
        for scene in production.scenes:
            firestore_svc.update_scene(production_id, scene.id, {"status": "generating"})
            video_uri = await ai_svc.generate_scene_video(production_id, scene)
            scene_uris.append(video_uri)
            firestore_svc.update_scene(production_id, scene.id, {"status": "completed", "video_url": video_uri})

        firestore_svc.update_production(production_id, {"status": ProjectStatus.STITCHING})
        final_uri = await ai_svc.stitch_production(production_id, scene_uris)
        
        firestore_svc.update_production(production_id, {
            "status": ProjectStatus.COMPLETED,
            "final_video_url": final_uri
        })
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        firestore_svc.update_production(production_id, {"status": ProjectStatus.FAILED, "error_message": str(e)})

# --- Endpoints ---

@app.get("/api/v1/productions", response_model=List[Project])
async def list_productions():
    if not firestore_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    return firestore_svc.get_productions()

@app.post("/api/v1/productions", response_model=Project)
async def create_production(project: Project):
    if not firestore_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.create_production(project)
    return project

@app.get("/api/v1/productions/{id}", response_model=Project)
async def get_production(id: str):
    if not firestore_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p: raise HTTPException(status_code=404)
    return p

@app.post("/api/v1/productions/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(id: str):
    if not firestore_svc or not ai_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    p = firestore_svc.get_production(id)
    if not p: raise HTTPException(status_code=404)
    
    firestore_svc.update_production(id, {"status": ProjectStatus.ANALYZING})
    result = await ai_svc.analyze_brief(id, p.base_concept, p.video_length, p.orientation)
    
    firestore_svc.update_production(id, {
        "scenes": [s.dict() for s in result.data],
        "status": ProjectStatus.SCRIPTED,
        "total_usage": result.usage.dict()
    })
    return result

@app.post("/api/v1/productions/{id}/scenes/{scene_id}/frame", response_model=AIResponseWrapper)
async def generate_scene_frame(id: str, scene_id: str):
    if not firestore_svc or not ai_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    production = firestore_svc.get_production(id)
    if not production: raise HTTPException(status_code=404)
    
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene: raise HTTPException(status_code=404)
    
    result = await ai_svc.generate_frame(id, scene.visual_description, production.orientation)
    firestore_svc.update_scene(id, scene_id, {"thumbnail_url": result.data})
    return result

@app.post("/api/v1/productions/{id}/render")
async def start_render(id: str, background_tasks: BackgroundTasks):
    if not firestore_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_sequential_generation, id)
    return {"status": "started"}

@app.post("/api/v1/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    if not storage_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = storage_svc.upload_file(content, destination, file.content_type)
    return {"gcs_uri": gcs_uri, "signed_url": storage_svc.get_signed_url(gcs_uri)}

# --- Diagnostic Endpoints ---

@app.post("/api/v1/diagnostics/optimize-prompt")
async def diagnostic_optimize(request: dict):
    if not ai_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    return await ai_svc.analyze_brief(
        "diag-proj", 
        request.get("concept", ""), 
        request.get("length", "16"), 
        request.get("orientation", "16:9")
    )

@app.post("/api/v1/diagnostics/generate-image")
async def diagnostic_image(request: dict):
    if not ai_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    return await ai_svc.generate_frame(
        "diag-proj", 
        request.get("prompt", ""), 
        request.get("orientation", "16:9")
    )

@app.post("/api/v1/diagnostics/generate-video")
async def diagnostic_video(request: dict):
    if not ai_svc or not storage_svc: raise HTTPException(status_code=503, detail="Service not initialized")
    scene = Scene(visual_description=request.get("prompt", ""), timestamp_start="0", timestamp_end="8")
    uri = await ai_svc.generate_scene_video("diag-proj", scene)
    return {"video_uri": uri, "signed_url": storage_svc.get_signed_url(uri)}

# --- SPA Serving ---
if os.path.exists("static"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join("static", full_path)
        if os.path.isfile(file_path): return FileResponse(file_path)
        return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    import uuid
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

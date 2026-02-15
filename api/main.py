import os
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List
from dotenv import load_dotenv

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

firestore_svc = FirestoreService()
ai_svc = AIService()
storage_svc = StorageService()

# --- Background Tasks ---

async def process_sequential_generation(production_id: str):
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
        firestore_svc.update_production(production_id, {"status": ProjectStatus.FAILED, "error_message": str(e)})

# --- Endpoints ---

@app.get("/api/v1/productions", response_model=List[Project])
async def list_productions():
    return firestore_svc.get_productions()

@app.post("/api/v1/productions", response_model=Project)
async def create_production(project: Project):
    firestore_svc.create_production(project)
    return project

@app.get("/api/v1/productions/{id}", response_model=Project)
async def get_production(id: str):
    p = firestore_svc.get_production(id)
    if not p: raise HTTPException(status_code=404)
    return p

@app.post("/api/v1/productions/{id}/analyze", response_model=AIResponseWrapper)
async def analyze_production(id: str):
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
    production = firestore_svc.get_production(id)
    if not production: raise HTTPException(status_code=404)
    
    scene = next((s for s in production.scenes if s.id == scene_id), None)
    if not scene: raise HTTPException(status_code=404)
    
    result = await ai_svc.generate_frame(id, scene.visual_description, production.orientation)
    firestore_svc.update_scene(id, scene_id, {"thumbnail_url": result.data})
    return result

@app.post("/api/v1/productions/{id}/render")
async def start_render(id: str, background_tasks: BackgroundTasks):
    firestore_svc.update_production(id, {"status": ProjectStatus.GENERATING})
    background_tasks.add_task(process_sequential_generation, id)
    return {"status": "started"}

@app.post("/api/v1/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = storage_svc.upload_file(content, destination, file.content_type)
    return {"gcs_uri": gcs_uri, "signed_url": storage_svc.get_signed_url(gcs_uri)}

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
    uvicorn.run(app, host="0.0.0.0", port=8080)

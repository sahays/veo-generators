import os
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path="../.env.dev")

from models import (
    Project, ProjectStatus, OptimizePromptRequest, OptimizePromptResponse,
    GenerateStoryboardRequest, GenerateVideoRequest, JobStatus, StoryboardFrame
)
from firestore_service import FirestoreService
from ai_service import AIService

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Veo Production API", version="1.0.0")

# Enable CORS for development (still useful if running front/back separately)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

firestore_svc = FirestoreService()
ai_svc = AIService()

# --- API Routes ---
@app.get("/api/v1/projects", response_model=List[Project])
async def list_projects():
    return firestore_svc.get_projects()

# ... (keep all existing @app.get/post/patch/delete routes here) ...

@app.get("/api/v1/configs/{category}", response_model=List[str])
async def get_config(category: str):
    return firestore_svc.get_config_options(category)

# --- Static File Serving ---
# Mount the static files directory (built React app)
# Note: In the Docker container, these will be in the 'static' folder
if os.path.exists("static"):
    app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Serve static files if they exist (favicon, etc)
        file_path = os.path.join("static", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise, serve index.html for React Router
        return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

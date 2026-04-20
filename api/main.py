import os
import logging
import warnings
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

import deps
from routers import (
    productions,
    scenes,
    render,
    uploads,
    key_moments,
    thumbnails,
    reframe,
    promo,
    adapts,
    system,
    diagnostics,
    auth,
    chat,
    models,
    pricing,
)

# Suppress the "non-text parts" warning from google-genai/adk which is noisy when using tools
warnings.filterwarnings("ignore", message=".*non-text parts in the response.*")

# Load environment variables
load_dotenv(dotenv_path="../.env.dev")

# Ensure Vertex AI configuration for google-adk/google-genai
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
if "GOOGLE_CLOUD_PROJECT" not in os.environ:
    os.environ["GOOGLE_CLOUD_PROJECT"] = os.getenv("GOOGLE_CLOUD_PROJECT", "")

# We set this globally for the ADK agents to use GEMINI_REGION for model calls
# Infrastructure services in deps.py already read the original value during startup
os.environ["GOOGLE_CLOUD_LOCATION"] = os.getenv("GEMINI_REGION", "us-central1")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Veo Production API", version="1.0.0")


# Bot protection middleware
class BotProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user_agent = request.headers.get("user-agent", "").lower()
        # Allow our own internal agent
        if "veoagent" in user_agent:
            return await call_next(request)

        bot_keywords = ["python-requests", "aiohttp", "httpx", "curl", "wget"]
        if any(keyword in user_agent for keyword in bot_keywords):
            return JSONResponse(
                status_code=403, content={"detail": "Automated access is not allowed"}
            )
        return await call_next(request)


app.add_middleware(BotProtectionMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Invite code validation middleware
@app.middleware("http")
async def validate_invite_code(request: Request, call_next):
    # Skip validation for health check, docs, and static files
    path = request.url.path
    if path in [
        "/health",
        "/docs",
        "/openapi.json",
        "/api/v1/auth/validate",
    ] or path.startswith("/static"):
        return await call_next(request)

    # Skip for direct asset access
    if "." in path.split("/")[-1] and not path.startswith("/api"):
        return await call_next(request)

    invite_code = request.headers.get("X-Invite-Code")
    if not invite_code:
        # Check if it's a browser request for a page (not API)
        if "text/html" in request.headers.get("accept", "") and not path.startswith(
            "/api"
        ):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Invite code required"})

    # Validate via the auth module (handles master code + Firestore + is_active)
    from routers.auth import validate_code

    result = validate_code(invite_code)
    if not result["valid"]:
        return JSONResponse(status_code=401, content={"detail": "Invalid invite code"})
    request.state.invite_code = invite_code
    request.state.is_master = result.get("is_master", False)

    response = await call_next(request)
    return response


# Include all routers
for r in [
    productions,
    scenes,
    render,
    uploads,
    key_moments,
    thumbnails,
    reframe,
    promo,
    adapts,
    system,
    diagnostics,
    auth,
    chat,
    models,
    pricing,
]:
    app.include_router(r.router)


@app.on_event("startup")
async def startup_event():
    deps.init_services()


@app.get("/health")
async def health_check():
    return {"status": "ok", "services": deps.services_ready()}


# Serve static files from the 'static' directory
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # If it's an API call that wasn't caught by a router, it's a 404
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # Check if the file exists in static
        file_path = os.path.join("static", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)

        # Otherwise, serve index.html for client-side routing
        return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

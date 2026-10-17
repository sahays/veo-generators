import os
import logging
import warnings
from typing import Any, Callable
from fastapi import FastAPI, Request, Response
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
    dubbing,
    system,
    diagnostics,
    auth,
    chat,
    models,
    pricing,
    avatars,
    avatars_live,
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

# Methods that mutate state — restricted to master users by default.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# POST endpoints that don't mutate persistent state and are safe for guests.
READ_ONLY_WRITES = {
    "/api/v1/auth/validate",
    "/api/v1/pricing/estimate",
    "/api/v1/chat/share",
}

# Path prefixes that require a privileged user (master OR power) on every
# method, including reads.
PRIVILEGED_ONLY_PREFIXES = ("/api/v1/avatars",)
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/api/v1/auth/validate"}


class BotProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[..., Any]
    ) -> Response:
        user_agent = request.headers.get("user-agent", "").lower()
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


def _is_exempt_path(request: Request) -> bool:
    """Return True if the request path bypasses invite-code validation."""
    path = request.url.path
    if (
        path in PUBLIC_PATHS
        or (path.startswith("/api/v1/chat/share/") and request.method == "GET")
        or path.startswith("/static")
        or path.startswith("/_next")
    ):
        return True
    if "." in path.split("/")[-1] and not path.startswith("/api"):
        return True
    return False


def _check_access_permissions(
    request: Request, is_privileged: bool
) -> JSONResponse | None:
    """Return a 403 JSONResponse if the user lacks privilege for the path/method."""
    path = request.url.path
    if not is_privileged and any(
        path.startswith(prefix) for prefix in PRIVILEGED_ONLY_PREFIXES
    ):
        return JSONResponse(
            status_code=403, content={"detail": "Privileged access required"}
        )
    if (
        request.method in WRITE_METHODS
        and path not in READ_ONLY_WRITES
        and not is_privileged
    ):
        return JSONResponse(
            status_code=403, content={"detail": "Privileged access required"}
        )
    return None


@app.middleware("http")
async def validate_invite_code(
    request: Request, call_next: Callable[..., Any]
) -> Response:
    if _is_exempt_path(request):
        return await call_next(request)

    path = request.url.path
    invite_code = request.headers.get("X-Invite-Code")
    if not invite_code:
        if "text/html" in request.headers.get("accept", "") and not path.startswith(
            "/api"
        ):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Invite code required"})

    from routers.auth import validate_code

    result = validate_code(invite_code)
    if not result["valid"]:
        return JSONResponse(status_code=401, content={"detail": "Invalid invite code"})
    request.state.invite_code = invite_code
    request.state.is_master = result.get("is_master", False)
    request.state.is_power = result.get("is_power", False)
    is_privileged = request.state.is_master or request.state.is_power
    denied = _check_access_permissions(request, is_privileged)
    if denied is not None:
        return denied
    return await call_next(request)


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
    dubbing,
    system,
    diagnostics,
    auth,
    chat,
    models,
    pricing,
    avatars,
    avatars_live,
]:
    app.include_router(r.router)


@app.on_event("startup")
async def startup_event() -> None:
    deps.init_services()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    from agents.tools import close_client

    await close_client()


@app.get("/health")
async def health_check() -> dict[str, Any]:
    return {"status": "ok", "services": deps.services_ready()}


# Serve static files from the 'static' directory
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        file_path = os.path.join("static", full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

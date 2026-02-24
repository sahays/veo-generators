import os
import re
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv

import deps
from routers import (
    productions,
    scenes,
    render,
    uploads,
    key_moments,
    thumbnails,
    system,
    diagnostics,
    auth,
)

# Load environment variables
load_dotenv(dotenv_path="../.env.dev")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Veo Production API", version="1.0.0")

# --- Rate Limiting ---
app.state.limiter = deps.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Exempt health check from rate limiting
@deps.limiter.request_filter
def _health_check_filter(request: Request) -> bool:
    return request.url.path == "/health"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InviteCodeMiddleware(BaseHTTPMiddleware):
    EXEMPT_PATHS = {"/health", "/api/v1/auth/validate"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Always allow CORS preflight requests through
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip non-API paths (SPA static files) and exempt paths
        if not path.startswith("/api/") or path in self.EXEMPT_PATHS:
            return await call_next(request)

        code = request.headers.get("X-Invite-Code", "")
        if not code:
            logger.warning(f"Auth: missing invite code for {request.method} {path}")
            return JSONResponse(
                status_code=403, content={"detail": "Invite code required"}
            )

        from routers.auth import validate_code

        result = validate_code(code)
        if not result["valid"]:
            logger.warning(f"Auth: invalid invite code for {request.method} {path}")
            return JSONResponse(
                status_code=403, content={"detail": "Invalid invite code"}
            )

        return await call_next(request)


BOT_UA_PATTERN = re.compile(
    r"bot|crawl|spider|slurp|scraper|wget|curl|httpie|python-requests"
    r"|go-http-client|node-fetch|axios|scrapy|phantomjs|headlesschrome",
    re.IGNORECASE,
)


class BotProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        ua = request.headers.get("User-Agent", "")
        if not ua or BOT_UA_PATTERN.search(ua):
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})
        return await call_next(request)


app.add_middleware(BotProtectionMiddleware)
app.add_middleware(InviteCodeMiddleware)

# Register routers
for r in [
    productions,
    scenes,
    render,
    uploads,
    key_moments,
    thumbnails,
    system,
    diagnostics,
    auth,
]:
    app.include_router(r.router)


@app.on_event("startup")
async def startup_event():
    try:
        deps.init_services()
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        # We don't raise here to allow the app to start and serve health checks
        # But endpoints relying on these will fail.


@app.get("/health")
async def health_check():
    return {
        "status": "healthy" if deps.services_ready() else "degraded",
        "services_initialized": deps.services_ready(),
    }


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

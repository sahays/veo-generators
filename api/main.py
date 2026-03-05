import os
import re
import logging
from datetime import datetime, timedelta, timezone

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Credit costs per endpoint: video=5, image=2, text=1, stitch=0, render=-1 (dynamic)
ENDPOINT_CREDITS: dict[str, int] = {
    # Text analysis (Gemini) — 1 credit
    "POST /api/v1/productions/{id}/analyze": 1,
    "POST /api/v1/key-moments/analyze": 1,
    "POST /api/v1/thumbnails/analyze": 1,
    "POST /api/v1/diagnostics/optimize-prompt": 1,
    # Image generation (Imagen) — 2 credits
    "POST /api/v1/productions/{id}/scenes/{scene_id}/frame": 2,
    "POST /api/v1/thumbnails/{id}/collage": 2,
    "POST /api/v1/diagnostics/generate-image": 2,
    # Video generation (Veo) — 5 credits
    "POST /api/v1/productions/{id}/scenes/{scene_id}/video": 5,
    "POST /api/v1/diagnostics/generate-video": 5,
    # Render — dynamic cost (5 × scenes without video_url)
    "POST /api/v1/productions/{id}/render": -1,
    # Stitch — no AI, 0 credits
    "POST /api/v1/productions/{id}/stitch": 0,
}

# Compile path patterns into regexes for matching
_CREDIT_REGEXES: list[tuple[str, re.Pattern, int]] = []
for entry, credits in ENDPOINT_CREDITS.items():
    method, path_template = entry.split(" ", 1)
    regex_str = re.sub(r"\{[^}]+\}", r"([^/]+)", path_template)
    _CREDIT_REGEXES.append((method, re.compile(f"^{regex_str}$"), credits))


def _get_credit_cost(method: str, path: str) -> int | None:
    """Return credit cost for a request, or None if not a credit-consuming endpoint."""
    for m, pattern, credits in _CREDIT_REGEXES:
        match = pattern.match(path)
        if method == m and match:
            if credits == -1:
                # Dynamic cost for render: 5 × scenes without video_url
                return _get_render_cost(match.group(1))
            return credits
    return None


def _get_render_cost(production_id: str) -> int:
    """Calculate render cost: 5 credits per scene without a video_url."""
    if not deps.firestore_svc:
        return 0
    production = deps.firestore_svc.get_production(production_id)
    if not production:
        return 0
    scenes_needing_video = sum(1 for s in production.scenes if not s.video_url)
    return scenes_needing_video * 5


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

        # Store auth info on request state for downstream use
        request.state.is_master = result.get("is_master", False)
        request.state.invite_code = code

        # Credit-based daily quota check
        credit_cost = _get_credit_cost(request.method, path)
        if credit_cost is not None and credit_cost > 0 and deps.firestore_svc:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            current_usage = deps.firestore_svc.get_daily_usage(code, today)

            if not request.state.is_master:
                invite = deps.firestore_svc.get_invite_code_by_value(code)
                daily_credits = invite.daily_credits if invite else 250

                if current_usage + credit_cost > daily_credits:
                    now = datetime.now(timezone.utc)
                    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    next_midnight = midnight + timedelta(days=1)
                    retry_after = int((next_midnight - now).total_seconds())

                    logger.warning(
                        f"Quota exceeded for code '{code}': "
                        f"{current_usage}+{credit_cost}/{daily_credits} on {today}"
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": (
                                f"Daily credit quota exceeded "
                                f"({current_usage}/{daily_credits} credits used). "
                                f"Resets at midnight UTC."
                            ),
                            "credits_used": current_usage,
                            "daily_credits": daily_credits,
                            "credit_cost": credit_cost,
                        },
                        headers={"Retry-After": str(retry_after)},
                    )

            # Store cost info; increment only after successful response
            request.state.credit_cost = credit_cost
            request.state.credit_date = today

        response = await call_next(request)

        # Only charge credits if the action succeeded (2xx)
        pending_cost = getattr(request.state, "credit_cost", None)
        if pending_cost and deps.firestore_svc and 200 <= response.status_code < 300:
            deps.firestore_svc.increment_daily_usage(
                code, request.state.credit_date, pending_cost
            )

        return response


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

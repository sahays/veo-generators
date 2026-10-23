"""Dedicated Cloud Run microservice (`veo-generators-productions`) for the Story-to-Video Graph System.

Cascades HTTP routes (`routers.productions`) -> orchestration service (`services.productions_service`)
-> StoryGraph pipeline (`storygraph.pipeline`) and repository (`storygraph.repo`).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from routers import details_router, productions_router
from services import build_pipeline, get_repo

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Veo Generators — Story-to-Video Graph Productions Service",
)
# Snapshot JSON compresses ~7x; the Next.js server-action fetch negotiates gzip transparently.
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Static `.../shots/{shot_id}/runs` must not be shadowed by a parameterised productions route.
app.include_router(details_router)
app.include_router(productions_router)

__all__ = ["app", "build_pipeline", "get_repo"]


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "veo-generators-productions",
        "engine": "storygraph-v1",
    }

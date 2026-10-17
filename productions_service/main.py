"""Dedicated Cloud Run microservice (`veo-generators-productions`) for the Story-to-Video Graph System.

Cascades HTTP routes (`routers.productions`) -> orchestration service (`services.productions_service`)
-> StoryGraph pipeline (`storygraph.pipeline`) and repository (`storygraph.repo`).
"""

from __future__ import annotations

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from routers import productions_router
from services import build_pipeline, get_repo

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Veo Generators — Story-to-Video Graph Productions Service",
)
app.include_router(productions_router)

__all__ = ["app", "build_pipeline", "get_repo"]


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "healthy",
        "service": "veo-generators-productions",
        "engine": "storygraph-v1",
    }

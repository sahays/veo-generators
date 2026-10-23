"""FastAPI routers for the Story-to-Video Graph Productions microservice."""

from .details import router as details_router
from .productions import router as productions_router

__all__ = ["details_router", "productions_router"]

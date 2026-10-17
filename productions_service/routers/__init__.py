"""FastAPI routers for the Story-to-Video Graph Productions microservice."""

from .productions import router as productions_router

__all__ = ["productions_router"]

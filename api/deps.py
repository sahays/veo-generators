import os
import logging

from firestore_service import FirestoreService
from ai_service import AIService
from video_service import VideoService
from transcoder_service import TranscoderService
from storage_service import StorageService

logger = logging.getLogger(__name__)

# Global service instances (initialized on startup)
firestore_svc: FirestoreService | None = None
ai_svc: AIService | None = None
video_svc: VideoService | None = None
transcoder_svc: TranscoderService | None = None
storage_svc: StorageService | None = None


def init_services():
    """Instantiate all backend services. Called once during FastAPI startup."""
    global firestore_svc, ai_svc, video_svc, transcoder_svc, storage_svc
    logger.info("Initializing services...")
    firestore_svc = FirestoreService()
    storage_svc = StorageService()
    ai_svc = AIService(storage_svc=storage_svc, firestore_svc=firestore_svc)
    video_svc = VideoService(storage_svc=storage_svc)
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
    transcoder_svc = TranscoderService(project_id, location)
    logger.info("Services initialized successfully.")


def services_ready() -> bool:
    """Return True if all services were initialised successfully."""
    return all([firestore_svc, ai_svc, video_svc, transcoder_svc, storage_svc])

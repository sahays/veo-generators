import os
import logging

from firestore_service import FirestoreService
from gemini_service import GeminiService
from video_service import VideoService
from transcoder_service import TranscoderService
from storage_service import StorageService
from diarization_service import DiarizationService

logger = logging.getLogger(__name__)

# Capture the real cloud region at import time.  main.py later overwrites
# GOOGLE_CLOUD_LOCATION for the genai/ADK SDK, so infrastructure services
# (Transcoder, Diarization) must use this snapshot instead.
_INFRA_REGION = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")

# Global service instances (initialized on startup)
firestore_svc: FirestoreService | None = None
gemini_svc: GeminiService | None = None
video_svc: VideoService | None = None
transcoder_svc: TranscoderService | None = None
storage_svc: StorageService | None = None
diarization_svc: DiarizationService | None = None

# Backward-compatible alias
ai_svc = None


def init_services():
    """Instantiate all backend services. Called once during FastAPI startup."""
    global firestore_svc, gemini_svc, ai_svc, video_svc, transcoder_svc
    global storage_svc, diarization_svc
    logger.info("Initializing services...")
    firestore_svc = FirestoreService()
    storage_svc = StorageService()
    gemini_svc = GeminiService(storage_svc=storage_svc, firestore_svc=firestore_svc)
    ai_svc = gemini_svc  # alias for existing code
    video_svc = VideoService(storage_svc=storage_svc, firestore_svc=firestore_svc)
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    # Use the region captured at import time (before main.py overrides
    # GOOGLE_CLOUD_LOCATION for the genai/ADK SDK).
    location = _INFRA_REGION
    transcoder_svc = TranscoderService(project_id, location)
    diarization_svc = DiarizationService(project_id, location)
    logger.info("Services initialized successfully.")


def services_ready() -> bool:
    """Return True if all services were initialised successfully."""
    return all([firestore_svc, gemini_svc, video_svc, transcoder_svc, storage_svc])

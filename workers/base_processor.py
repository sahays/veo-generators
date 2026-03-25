"""
Base class for worker job processors and shared utilities.
"""

import logging
import pathlib
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)


class TempFileManager:
    """Tracks temporary files and cleans them up."""

    def __init__(self):
        self.files: list[str] = []

    def create(self, suffix: str = ".mp4") -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        path = tmp.name
        tmp.close()
        self.files.append(path)
        return path

    def cleanup(self) -> None:
        for f in self.files:
            try:
                pathlib.Path(f).unlink(missing_ok=True)
            except Exception:
                pass
        self.files.clear()


class JobProcessor(ABC):
    """Base class for all worker job processors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Job type name for logging (e.g. 'reframe', 'promo')."""

    @abstractmethod
    def get_pending_records(self) -> list:
        """Fetch pending records from Firestore."""

    @abstractmethod
    def process(self, record) -> None:
        """Process a single job record."""

    @abstractmethod
    def update_status(
        self, record_id: str, status: str, progress: int, **extra
    ) -> None:
        """Update job status in Firestore."""

    @abstractmethod
    def mark_failed(self, record_id: str, error_message: str) -> None:
        """Mark a job as failed."""

    def _set_completion_timestamp(self, updates: dict, status: str) -> None:
        """Add completedAt to updates dict for terminal statuses."""
        if status in ("completed", "failed"):
            updates["completedAt"] = datetime.utcnow()

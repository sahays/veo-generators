"""Base class for worker job processors and shared utilities."""

import logging
import pathlib
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime

import deps

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
    """Base class for all worker job processors.

    Subclasses declare `firestore_update_method` (the `FirestoreService`
    method name that persists record updates), `name`, plus implement
    `get_pending_records` and `process`. Everything else (status updates,
    failure marking, completion timestamps) is shared.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Job type name for logging (e.g. 'reframe', 'promo')."""

    @property
    @abstractmethod
    def firestore_update_method(self) -> str:
        """Name of the FirestoreService method that updates this record type."""

    @abstractmethod
    def get_pending_records(self) -> list:
        """Fetch pending records from Firestore."""

    @abstractmethod
    def process(self, record) -> None:
        """Process a single job record."""

    def update_status(
        self, record_id: str, status: str, progress: int, **extra
    ) -> None:
        """Persist status/progress updates, adding completedAt on terminal states."""
        updates = {"status": status, "progress_pct": progress, **extra}
        self._set_completion_timestamp(updates, status)
        getattr(deps.firestore_svc, self.firestore_update_method)(record_id, updates)

    def mark_failed(self, record_id: str, error_message: str) -> None:
        self.update_status(record_id, "failed", 0, error_message=error_message)

    def _set_completion_timestamp(self, updates: dict, status: str) -> None:
        """Add completedAt to updates dict for terminal statuses."""
        if status in ("completed", "failed"):
            updates["completedAt"] = datetime.utcnow()

"""Abstract protocols and filter primitives for GraphStore and BlobStore."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Literal, Protocol

FilterOp = Literal["==", "in", "array_contains", ">=", "<="]
Filter = tuple[str, FilterOp, Any]

COLLECTIONS: dict[str, str] = {
    "Entity": "entities",
    "Event": "events",
    "StateFact": "state_facts",
    "Appearance": "appearances",
    "Asset": "assets",
    "StyleGuide": "meta",  # doc_id == "style_guide"
    "Scene": "scenes",
    "DialogueLine": "dialogue_lines",
    "MusicCue": "music_cues",
    "Shot": "shots",
    "GenerationRun": "generation_runs",
    "ChangeRequest": "change_requests",
    "Gate": "gates",
    "StageRun": "stage_runs",
    "AuditEntry": "audit_log",
    "PromptVersion": "prompt_versions",
}


class BatchWriter(Protocol):
    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, collection: str, doc_id: str) -> None: ...


class Tx(BatchWriter, Protocol):
    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...


class GraphStore(Protocol):
    project_id: str

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None: ...

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None: ...

    def delete(self, collection: str, doc_id: str) -> None: ...

    def query(
        self,
        collection: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def batch(self) -> AbstractContextManager[BatchWriter]: ...

    def transaction(self) -> AbstractContextManager[Tx]: ...


class BlobStore(Protocol):
    def put_bytes(self, rel_path: str, data: bytes, content_type: str) -> str:
        """Store bytes and return a canonical URI (`gs://...` or `file://...`)."""
        ...

    def get_bytes(self, uri: str) -> bytes: ...

    def exists(self, uri: str) -> bool: ...

"""In-memory GraphStore implementation matching Firestore semantics."""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ..errors import DocTooLarge
from .base import BatchWriter, Filter, Tx
from .codec import check_doc_size


def _matches_filter(doc: dict[str, Any], flt: Filter) -> bool:
    field, op, val = flt
    actual = doc.get(field)
    if op == "==":
        return actual == val
    if op == "in":
        if not isinstance(val, (list, tuple, set)):
            return False
        if len(val) > 30:
            raise ValueError("Firestore 'in' filter supports at most 30 elements")
        return actual in val
    if op == "array_contains":
        return isinstance(actual, list) and val in actual
    if op == ">=":
        return actual is not None and actual >= val
    if op == "<=":
        return actual is not None and actual <= val
    raise ValueError(f"Unsupported filter operator: {op!r}")


class _MemoryBatch(BatchWriter):
    def __init__(self, store: MemoryStore) -> None:
        self._store = store
        self._ops: list[tuple[str, str, str, dict[str, Any] | None]] = []

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        check_doc_size(data, max_bytes=self._store.max_doc_bytes)
        self._ops.append(("set", collection, doc_id, copy.deepcopy(data)))

    def delete(self, collection: str, doc_id: str) -> None:
        self._ops.append(("delete", collection, doc_id, None))

    def commit(self) -> None:
        for kind, col, doc_id, payload in self._ops:
            if kind == "set" and payload is not None:
                self._store._data.setdefault(col, {})[doc_id] = payload
            elif kind == "delete":
                self._store._data.get(col, {}).pop(doc_id, None)


class _MemoryTx(_MemoryBatch, Tx):
    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        # Check staged writes in this transaction first, or read underlying store
        for kind, col, did, payload in reversed(self._ops):
            if col == collection and did == doc_id:
                return copy.deepcopy(payload) if kind == "set" else None
        raw = self._store._data.get(collection, {}).get(doc_id)
        return copy.deepcopy(raw) if raw is not None else None


class MemoryStore:
    """Thread-safe in-memory GraphStore with identical semantics to FirestoreStore."""

    _GLOBAL_PROJECTS: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    _GLOBAL_LOCK = threading.RLock()

    def __init__(
        self,
        project_id: str,
        max_doc_bytes: int = 900_000,
        shared: bool = False,
    ) -> None:
        self.project_id = project_id
        self.max_doc_bytes = max_doc_bytes
        self._lock = self._GLOBAL_LOCK if shared else threading.RLock()
        if shared:
            with self._GLOBAL_LOCK:
                self._data = self._GLOBAL_PROJECTS.setdefault(project_id, {})
        else:
            self._data: dict[str, dict[str, dict[str, Any]]] = {}

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._data.get(collection, {}).get(doc_id)
            return copy.deepcopy(doc) if doc is not None else None

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        check_doc_size(data, max_bytes=self.max_doc_bytes)
        if len(data) == 0 and self.max_doc_bytes < 0:
            raise DocTooLarge("Invalid max_doc_bytes")
        with self._lock:
            self._data.setdefault(collection, {})[doc_id] = copy.deepcopy(data)

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._data.get(collection, {}).pop(doc_id, None)

    def query(
        self,
        collection: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            docs = [
                copy.deepcopy(d)
                for d in self._data.get(collection, {}).values()
                if all(_matches_filter(d, f) for f in (filters or []))
            ]
        if order_by:
            desc = order_by.startswith("-")
            key_field = order_by[1:] if desc else order_by
            docs.sort(
                key=lambda d: (d.get(key_field) is None, d.get(key_field)),
                reverse=desc,
            )
        if limit is not None:
            docs = docs[:limit]
        return docs

    @contextmanager
    def batch(self) -> Iterator[BatchWriter]:
        with self._lock:
            b = _MemoryBatch(self)
            yield b
            b.commit()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        with self._lock:
            tx = _MemoryTx(self)
            yield tx
            tx.commit()

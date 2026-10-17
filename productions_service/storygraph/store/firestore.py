"""Google Cloud Firestore implementation of GraphStore."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from .base import BatchWriter, Filter, Tx
from .codec import check_doc_size

_BATCH_LIMIT = 450


class _FirestoreAutoChunkBatch(BatchWriter):
    def __init__(self, store: FirestoreStore) -> None:
        self._store = store
        self._ops: list[tuple[str, Any, dict[str, Any] | None]] = []

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        check_doc_size(data, max_bytes=self._store.max_doc_bytes)
        ref = self._store._col(collection).document(doc_id)
        self._ops.append(("set", ref, data))

    def delete(self, collection: str, doc_id: str) -> None:
        ref = self._store._col(collection).document(doc_id)
        self._ops.append(("delete", ref, None))

    def commit(self) -> None:
        for i in range(0, len(self._ops), _BATCH_LIMIT):
            chunk = self._ops[i : i + _BATCH_LIMIT]
            b = self._store._db.batch()
            for kind, ref, data in chunk:
                if kind == "set" and data is not None:
                    b.set(ref, data)
                elif kind == "delete":
                    b.delete(ref)
            b.commit()


class _FirestoreTx(Tx):
    def __init__(self, store: FirestoreStore, tx: firestore.Transaction) -> None:
        self._store = store
        self._tx = tx
        self._staged: dict[tuple[str, str], dict[str, Any] | None] = {}

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        key = (collection, doc_id)
        if key in self._staged:
            return self._staged[key]
        ref = self._store._col(collection).document(doc_id)
        snap = ref.get(transaction=self._tx)
        return snap.to_dict() if snap.exists else None

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        check_doc_size(data, max_bytes=self._store.max_doc_bytes)
        ref = self._store._col(collection).document(doc_id)
        self._tx.set(ref, data)
        self._staged[(collection, doc_id)] = data

    def delete(self, collection: str, doc_id: str) -> None:
        ref = self._store._col(collection).document(doc_id)
        self._tx.delete(ref)
        self._staged[(collection, doc_id)] = None


class FirestoreStore:
    """Firestore-backed GraphStore scoped under `{collection_prefix}/{project_id}/{subcollection}/{doc_id}`."""

    def __init__(
        self,
        project_id: str,
        gcp_project: str | None = None,
        database: str = "(default)",
        collection_prefix: str = "veo_generators_productions",
        max_doc_bytes: int = 900_000,
        client: firestore.Client | None = None,
    ) -> None:
        self.project_id = project_id
        self.collection_prefix = collection_prefix
        self.max_doc_bytes = max_doc_bytes
        self._db = client or firestore.Client(project=gcp_project, database=database)
        self._root = self._db.collection(collection_prefix).document(project_id)

    def _col(self, collection: str):
        return self._root.collection(collection)

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        snap = self._col(collection).document(doc_id).get()
        return snap.to_dict() if snap.exists else None

    def set(self, collection: str, doc_id: str, data: dict[str, Any]) -> None:
        check_doc_size(data, max_bytes=self.max_doc_bytes)
        self._col(collection).document(doc_id).set(data)

    def delete(self, collection: str, doc_id: str) -> None:
        self._col(collection).document(doc_id).delete()

    def query(
        self,
        collection: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        q: Any = self._col(collection)
        flt_list = list(filters or [])
        for _f, op, val in flt_list:
            if op == "in" and isinstance(val, (list, tuple, set)) and len(val) > 30:
                raise ValueError("Firestore 'in' filter supports at most 30 elements")

        if not flt_list:
            if order_by:
                desc = order_by.startswith("-")
                key_field = order_by[1:] if desc else order_by
                direction = (
                    firestore.Query.DESCENDING if desc else firestore.Query.ASCENDING
                )
                q = q.order_by(key_field, direction=direction)
            if limit is not None:
                q = q.limit(limit)
            return [snap.to_dict() for snap in q.stream() if snap.exists]

        # Push first filter to Firestore (single-field index is automatic); evaluate remaining filters & sort in-memory to avoid composite-index errors
        f0_field, f0_op, f0_val = flt_list[0]
        q = q.where(filter=FieldFilter(f0_field, f0_op, f0_val))
        rows = [snap.to_dict() for snap in q.stream() if snap.exists]

        for field, op, val in flt_list[1:]:
            if op == "==":
                rows = [r for r in rows if r.get(field) == val]
            elif op == "!=":
                rows = [r for r in rows if r.get(field) != val]
            elif op == "in":
                rows = [r for r in rows if r.get(field) in val]
            elif op == "<=":
                rows = [
                    r for r in rows if r.get(field) is not None and r.get(field) <= val
                ]
            elif op == ">=":
                rows = [
                    r for r in rows if r.get(field) is not None and r.get(field) >= val
                ]

        if order_by:
            desc = order_by.startswith("-")
            key_field = order_by[1:] if desc else order_by
            rows.sort(
                key=lambda r: (r.get(key_field) is None, r.get(key_field)), reverse=desc
            )
        if limit is not None:
            rows = rows[:limit]
        return rows

    @contextmanager
    def batch(self) -> Iterator[BatchWriter]:
        b = _FirestoreAutoChunkBatch(self)
        yield b
        b.commit()

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        tx = self._db.transaction()
        with tx:
            yield _FirestoreTx(self, tx)

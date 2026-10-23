"""One-shot bounded-parallel collection reads and a read-only GraphStore view over them.

The snapshot (and the validators/integrity checks it runs) used to issue ~640 sequential
Firestore round trips per request, many of them N+1 point reads. `prefetch` reads each
collection exactly once, concurrently; `PrefetchedStore` then answers every later `get`/`query`
from memory with Firestore semantics, falling through to the real store only for data that was
not prefetched (so correctness never depends on the prefetch list being complete).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from storygraph.store.base import BatchWriter, Filter, GraphStore, Tx
from storygraph.store.memory import apply_query

PREFETCH_MAX_WORKERS: int = 8
Row = dict[str, Any]
DocKey = tuple[str, str]


class ReadOnlySnapshotError(RuntimeError):
    """Raised when snapshot shaping code attempts a write through the read-only view."""


@dataclass(frozen=True)
class QuerySpec:
    """One collection read. Specs with a `limit` are never used to answer later queries."""

    collection: str
    filters: tuple[Filter, ...] = ()
    order_by: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class Prefetched:
    rows: dict[str, list[Row]]  # keyed by spec name
    docs: dict[DocKey, Row | None]


def prefetch(
    store: GraphStore,
    specs: dict[str, QuerySpec],
    docs: tuple[DocKey, ...] = (),
    max_workers: int = PREFETCH_MAX_WORKERS,
) -> Prefetched:
    """Run every query and point read concurrently on a bounded pool (one round trip each)."""
    workers = max(1, min(max_workers, len(specs) + len(docs)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        row_futs: dict[str, Future[list[Row]]] = {
            name: pool.submit(_run_spec(store, spec)) for name, spec in specs.items()
        }
        doc_futs: dict[DocKey, Future[Row | None]] = {
            key: pool.submit(store.get, key[0], key[1]) for key in docs
        }
        return Prefetched(
            rows={name: fut.result() for name, fut in row_futs.items()},
            docs={key: fut.result() for key, fut in doc_futs.items()},
        )


def _run_spec(store: GraphStore, spec: QuerySpec) -> Callable[[], list[Row]]:
    return lambda: store.query(
        spec.collection, list(spec.filters) or None, spec.order_by, spec.limit
    )


class PrefetchedStore:
    """Read-only GraphStore answering from prefetched rows; misses delegate to `inner`.

    A collection prefetched with filters F serves only queries whose filters include F, so
    a partial read (e.g. active prompt versions) is never mistaken for the full collection.
    Rows are shared, not copied: callers must treat them as immutable (writes raise).
    """

    def __init__(
        self, inner: GraphStore, data: Prefetched, specs: dict[str, QuerySpec]
    ) -> None:
        self.project_id = inner.project_id
        self.max_doc_bytes: int = getattr(inner, "max_doc_bytes", 900_000)
        self._inner = inner
        self._docs = data.docs
        self._served: dict[str, tuple[tuple[Filter, ...], list[Row]]] = {
            s.collection: (s.filters, data.rows[name])
            for name, s in specs.items()
            if s.limit is None
        }
        self._by_id: dict[str, dict[str, Row]] = {
            col: {str(r.get("id")): r for r in rows}
            for col, (flts, rows) in self._served.items()
            if not flts
        }

    def get(self, collection: str, doc_id: str) -> Row | None:
        if (collection, doc_id) in self._docs:
            return self._docs[(collection, doc_id)]
        index = self._by_id.get(collection)
        if index is not None:
            return index.get(doc_id)
        return self._inner.get(collection, doc_id)

    def query(
        self,
        collection: str,
        filters: list[Filter] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[Row]:
        served = self._served.get(collection)
        wanted = list(filters or [])
        if served is None or not all(f in wanted for f in served[0]):
            return self._inner.query(collection, filters, order_by, limit)
        return apply_query(served[1], wanted, order_by, limit)

    def set(self, collection: str, doc_id: str, data: Row) -> None:
        raise ReadOnlySnapshotError(f"snapshot view cannot write {collection}/{doc_id}")

    def delete(self, collection: str, doc_id: str) -> None:
        raise ReadOnlySnapshotError(
            f"snapshot view cannot delete {collection}/{doc_id}"
        )

    @contextmanager
    def batch(self) -> Iterator[BatchWriter]:
        raise ReadOnlySnapshotError("snapshot view cannot open a write batch")
        yield  # pragma: no cover - generator form required by contextmanager

    @contextmanager
    def transaction(self) -> Iterator[Tx]:
        raise ReadOnlySnapshotError("snapshot view cannot open a transaction")
        yield  # pragma: no cover - generator form required by contextmanager

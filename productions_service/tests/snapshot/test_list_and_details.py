"""List summaries stay O(productions); prefetched view semantics; audit cursor pages."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from services.details.audit_page import decode_cursor, paginate, query_window
from services.snapshot.prefetch import (
    PrefetchedStore,
    QuerySpec,
    ReadOnlySnapshotError,
    prefetch,
)
from services.snapshot.summary import summarize_projects
from storygraph.repo import Repo
from storygraph.schema import Asset, ProjectMeta, Role
from storygraph.store import LocalBlobStore, MemoryStore
from storygraph.store.memory import apply_query
from storygraph.store.url_signing import SignedUrlCache


class CountingStore(MemoryStore):
    """MemoryStore that counts reads per collection."""

    def __init__(self, project_id: str) -> None:
        super().__init__(project_id=project_id)
        self.reads: Counter[str] = Counter()

    def get(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        self.reads[collection] += 1
        return super().get(collection, doc_id)

    def query(self, collection: str, filters: Any = None, order_by: Any = None,
              limit: Any = None) -> list[dict[str, Any]]:  # fmt: skip
        self.reads[collection] += 1
        return super().query(collection, filters, order_by, limit)


def _project(tmp_path: Path, pid: str, archived: bool, kinds: list[str]) -> Repo:
    repo = Repo(store=CountingStore(pid), blobs=LocalBlobStore(tmp_path, pid))
    repo.put_project_meta(ProjectMeta(id=pid, name=pid, archived=archived))
    for i, kind in enumerate(kinds):
        repo.add_asset(Asset(
            id=f"{pid}_a{i}", created_by=Role.DESIGNER, kind=kind,  # type: ignore[arg-type]
            uri=f"gs://b/{pid}/{kind}.png", sha256="s", generation_prompt="p", model="m",
        ))  # fmt: skip
    for i in range(50):  # history that a summary must never read
        repo.store.set("generation_runs", f"r{i}", {"id": f"r{i}", "shot_id": "s"})
    repo.store.reads.clear()  # type: ignore[attr-defined]
    return repo


def test_list_summary_reads_meta_and_thumbnail_only(tmp_path: Path) -> None:
    live = _project(
        tmp_path, "p_live", False, ["first_frame", "character_sheet", "location_plate"]
    )
    old = _project(tmp_path, "p_old", True, ["character_sheet"])
    out = summarize_projects([live, old], include_archived=False)
    assert [s["id"] for s in out] == ["p_live"]
    assert out[0]["thumbnail_url"] == "gs://b/p_live/location_plate.png"
    assert "story_graph" not in out[0]
    assert set(live.store.reads) == {"meta", "assets"}  # type: ignore[attr-defined]
    assert set(old.store.reads) == {"meta"}  # archived: no thumbnail query
    both = summarize_projects([live, old], include_archived=True)
    assert {s["id"] for s in both} == {"p_live", "p_old"}


def test_prefetched_view_serves_memory_and_never_widens_partial_reads() -> None:
    inner = CountingStore("p")
    for i, status in enumerate(["active", "superseded", "superseded"]):
        inner.set(
            "prompt_versions",
            f"pv{i}",
            {"id": f"pv{i}", "status": status, "shot_id": "s"},
        )
    inner.set("shots", "s", {"id": "s", "story_order": 1})
    specs = {
        "shots": QuerySpec("shots"),
        "pv": QuerySpec("prompt_versions", (("status", "==", "active"),)),
    }
    view = PrefetchedStore(inner, prefetch(inner, specs), specs)
    inner.reads.clear()
    assert view.get("shots", "s") == {"id": "s", "story_order": 1}
    assert view.get("shots", "missing") is None
    assert len(view.query("prompt_versions", [("status", "==", "active")])) == 1
    assert sum(inner.reads.values()) == 0
    assert (
        len(view.query("prompt_versions", [("shot_id", "==", "s")])) == 3
    )  # delegated
    assert inner.reads["prompt_versions"] == 1
    with pytest.raises(ReadOnlySnapshotError):
        view.set("shots", "s", {})


def _audit_rows() -> list[dict[str, Any]]:
    ts = ["2026-10-20T10:00:03Z", "2026-10-20T10:00:02Z", "2026-10-20T10:00:02Z",
          "2026-10-20T10:00:02Z", "2026-10-20T10:00:01Z"]  # fmt: skip
    return [{"id": f"aud_{i}", "created_at": t} for i, t in enumerate(ts)]


def test_audit_pages_cover_every_entry_once_across_equal_timestamps() -> None:
    rows, seen, raw_cursor = _audit_rows(), [], None
    for _ in range(10):
        cursor = decode_cursor(raw_cursor)
        filters, row_limit = query_window(cursor, 2)
        page, nxt = paginate(
            apply_query(rows, filters, "-created_at", row_limit), cursor, 2
        )
        seen += [r["id"] for r in page]
        if nxt is None:
            break
        raw_cursor = nxt.encode()
    assert sorted(seen) == sorted(r["id"] for r in rows) and len(seen) == len(set(seen))


def test_audit_cursor_rejects_injected_values() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        decode_cursor("2026-10-20T10:00:02Z|aud_1,../../meta")


def test_signed_url_cache_expires_and_evicts_lru() -> None:
    now = [0.0]
    cache = SignedUrlCache(ttl_s=10, max_entries=2, clock=lambda: now[0])
    cache.put("a", "A")
    cache.put("b", "B")
    assert cache.get("a") == "A"  # refreshes LRU position of "a"
    cache.put("c", "C")
    assert cache.get("b") is None and cache.get("a") == "A"
    now[0] = 11
    assert cache.get("a") is None

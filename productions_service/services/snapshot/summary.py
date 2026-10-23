"""Lightweight per-production summaries for `GET /api/v1/productions` (never a full snapshot).

Cost per production: one meta point read + one small filtered asset query for the thumbnail,
run concurrently across productions on a bounded pool; all thumbnails/final cuts are then
signed in a single cached batch. O(productions), independent of history size.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from storygraph.repo import Repo
from storygraph.schema import ProjectMeta
from storygraph.store.url_signing import sign_all

from .sections import project_envelope

LIST_MAX_WORKERS = 8
# Thumbnail preference: establishing location plate, else a character sheet.
THUMBNAIL_KIND_RANK: dict[str, int] = {"location_plate": 0, "character_sheet": 1}


@dataclass(frozen=True)
class SummarySource:
    meta: ProjectMeta
    thumbnail_uri: str | None


def pick_thumbnail_uri(rows: Sequence[dict[str, Any]]) -> str | None:
    """Earliest-version asset of the most preferred thumbnail kind that has a URI."""
    candidates = [
        r for r in rows if r.get("uri") and r.get("kind") in THUMBNAIL_KIND_RANK
    ]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda r: (THUMBNAIL_KIND_RANK[str(r["kind"])], r.get("version") or 0),
    )
    return str(best["uri"])


def load_summary_source(repo: Repo, include_archived: bool) -> SummarySource | None:
    """Read meta (and the thumbnail candidates only for productions that will be listed)."""
    meta = repo.get_project_meta()
    if meta is None or (meta.archived and not include_archived):
        return None
    rows = repo.store.query(
        "assets", filters=[("kind", "in", list(THUMBNAIL_KIND_RANK))]
    )
    return SummarySource(meta=meta, thumbnail_uri=pick_thumbnail_uri(rows))


def build_summary(src: SummarySource, signed: dict[str, str]) -> dict[str, Any]:
    meta = src.meta
    final_url = signed.get(meta.final_video_uri or "") or meta.final_video_url
    return {
        **project_envelope(meta, meta.story_text or meta.base_concept, final_url),
        "thumbnail_url": signed.get(src.thumbnail_uri or ""),
    }


def summarize_projects(
    repos: Sequence[Repo], include_archived: bool
) -> list[dict[str, Any]]:
    """Summaries for `repos`, newest `updatedAt` first."""
    if not repos:
        return []
    with ThreadPoolExecutor(max_workers=min(LIST_MAX_WORKERS, len(repos))) as pool:
        loaded = pool.map(lambda r: load_summary_source(r, include_archived), repos)
        sources = [s for s in loaded if s is not None]
    uris = [u for s in sources for u in (s.thumbnail_uri, s.meta.final_video_uri) if u]
    signed = sign_all(repos[0].blobs, uris)
    out = [build_summary(s, signed) for s in sources]
    out.sort(key=lambda r: r["updatedAt"], reverse=True)
    return out

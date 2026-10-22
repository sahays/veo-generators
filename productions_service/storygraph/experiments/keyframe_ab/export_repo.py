"""Load a production export directory (Firestore REST dumps) into an in-memory `Repo`.

State facts are rebuilt from the exported Events (`rebuild_state_facts`) so the planner reads
the same deterministic state the pipeline would, not a possibly stale export snapshot.
"""

from __future__ import annotations

from pathlib import Path

from ...repo import Repo
from ...schema import ProjectMeta
from ...state import rebuild_state_facts
from ...store import MemoryStore
from ...store.base import BlobStore
from ..prompt_ab.cases import load_records

COLLECTIONS: tuple[str, ...] = (
    "entities",
    "events",
    "appearances",
    "assets",
    "scenes",
    "shots",
    "dialogue_lines",
    "prompt_versions",
    "generation_runs",
)


def load_export_repo(export_dir: Path, project_id: str, blobs: BlobStore) -> Repo:
    """In-memory `Repo` seeded from `export_dir/<collection>.json` files."""
    store = MemoryStore(project_id=project_id, max_doc_bytes=10_000_000)
    for col in COLLECTIONS:
        path = export_dir / f"{col}.json"
        if not path.is_file():
            continue
        for rec in load_records(path):
            store.set(col, str(rec.get("id") or rec.get("_id")), rec)
    repo = Repo(store=store, blobs=blobs)
    meta_path = export_dir / "meta.json"
    if meta_path.is_file():
        repo.put_project_meta(ProjectMeta.model_validate(load_records(meta_path)[0]))
    rebuild_state_facts(repo)
    return repo

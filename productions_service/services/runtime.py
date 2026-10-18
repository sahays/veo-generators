"""Runtime configuration, repository construction, and collection reset helpers."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from storygraph.config import Config
from storygraph.pipeline import Pipeline
from storygraph.repo import Repo
from storygraph.schema import ProjectMeta
from storygraph.store import (
    FirestoreStore,
    GcsBlobStore,
    LocalBlobStore,
    MemoryStore,
)

logger = logging.getLogger(__name__)

# Registry of known project IDs when running in memory mode
MEMORY_PROJECT_INDEX: set[str] = set()


def load_runtime_config() -> Config:
    """Load StoryGraph configuration with Cloud Run / environment variable overrides."""
    cfg = Config.load()
    is_cloud_run = bool(os.getenv("K_SERVICE"))
    has_gcp = is_cloud_run and bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    default_store = "firestore" if has_gcp else cfg.store.backend
    default_blobs = (
        "gcs" if (is_cloud_run and os.getenv("GCS_BUCKET")) else cfg.blobs.backend
    )
    default_provider = "gemini" if has_gcp else cfg.image.provider
    cfg.store.backend = os.getenv("STORYGRAPH_STORE_BACKEND", default_store)
    cfg.store.firestore_project = os.getenv(
        "GOOGLE_CLOUD_PROJECT", cfg.store.firestore_project
    )
    cfg.blobs.backend = os.getenv("STORYGRAPH_BLOB_BACKEND", default_blobs)
    cfg.blobs.gcs_bucket = os.getenv("GCS_BUCKET", cfg.blobs.gcs_bucket)
    cfg.image.provider = os.getenv("STORYGRAPH_IMAGE_PROVIDER", default_provider)
    cfg.video.provider = os.getenv(
        "STORYGRAPH_VIDEO_PROVIDER",
        "gemini" if has_gcp else cfg.video.provider,
    )
    if has_gcp:
        cfg.caps.shot_max_retries = 2
        cfg.caps.design_loop_max = 1
    return cfg


def _build_store_and_blobs(
    project_id: str, cfg: Config
) -> tuple[FirestoreStore | MemoryStore, GcsBlobStore | LocalBlobStore]:
    """Instantiate the configured GraphStore and BlobStore backends for a project."""
    if cfg.store.backend == "firestore" and cfg.store.firestore_project:
        store: FirestoreStore | MemoryStore = FirestoreStore(
            project_id=project_id,
            gcp_project=cfg.store.firestore_project,
            database=cfg.store.firestore_database,
            collection_prefix=cfg.store.collection_prefix,
            max_doc_bytes=cfg.store.max_doc_bytes,
        )
    else:
        store = MemoryStore(
            project_id=project_id,
            max_doc_bytes=cfg.store.max_doc_bytes,
            shared=True,
        )
    if cfg.blobs.backend == "gcs" and cfg.blobs.gcs_bucket:
        blobs: GcsBlobStore | LocalBlobStore = GcsBlobStore(
            bucket_name=cfg.blobs.gcs_bucket,
            project_id=project_id,
            prefix=cfg.blobs.gcs_prefix,
        )
    else:
        blobs = LocalBlobStore(root_dir=cfg.blobs.local_root, project_id=project_id)
    return store, blobs


def _seed_meta_from_firestore_doc(
    project_id: str, pdata: dict[str, object]
) -> tuple[ProjectMeta, str]:
    """Construct ProjectMeta and base_concept from a legacy Firestore document."""
    base_concept = str(pdata.get("base_concept") or "")
    ptype = str(pdata.get("type") or "movie")
    orient = str(pdata.get("orientation") or "16:9")
    meta = ProjectMeta(
        id=project_id,
        name=str(pdata.get("name") or project_id),
        type=ptype if ptype in ("movie", "advertizement", "social") else "movie",  # type: ignore[arg-type]
        base_concept=base_concept,
        story_text=base_concept,
        video_length=str(pdata.get("video_length") or "16"),
        orientation=orient if orient in ("16:9", "9:16") else "16:9",  # type: ignore[arg-type]
        language=str(pdata.get("language") or "en-IN"),
        auto_approve_gates=bool(pdata.get("auto_approve_gates", False)),
    )
    return meta, base_concept


def _auto_seed_firestore_project(
    repo: Repo, store: FirestoreStore, cfg: Config, project_id: str
) -> None:
    """Seed StoryGraph metadata from an existing Firestore production document when missing."""
    try:
        doc = store._root.get()
        if not doc.exists:
            doc = store._db.collection("productions").document(project_id).get()
        if doc.exists:
            meta, base_concept = _seed_meta_from_firestore_doc(
                project_id, doc.to_dict() or {}
            )
            repo.put_project_meta(meta)
            repo.put_source_text(base_concept)
            Pipeline(repo=repo, cfg=cfg).ingest_story(base_concept)
    except Exception as exc:
        logger.warning(
            "Failed to auto-seed StoryGraph from Firestore",
            extra={
                "who": "_auto_seed_firestore_project",
                "where": "productions_service.services.runtime",
                "what": project_id,
                "why": str(exc),
                "how": "firestore_doc_lookup",
            },
        )


def get_repo(project_id: str, cfg: Config | None = None) -> Repo:
    """Return a configured StoryGraph Repo for `project_id`."""
    c = cfg or load_runtime_config()
    store, blobs = _build_store_and_blobs(project_id, c)
    repo = Repo(store=store, blobs=blobs)
    if repo.get_project_meta() is None and isinstance(store, FirestoreStore):
        _auto_seed_firestore_project(repo, store, c, project_id)
    return repo


def build_pipeline(project_id: str) -> Pipeline:
    """Build a StoryGraph Pipeline instance for `project_id`."""
    cfg = load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    return Pipeline(repo=repo, cfg=cfg)


_RESETTABLE_COLLECTIONS: tuple[str, ...] = (
    "entities",
    "events",
    "state_facts",
    "appearances",
    "assets",
    "scenes",
    "dialogue_lines",
    "music_cues",
    "shots",
    "generation_runs",
    "change_requests",
    "gates",
    "stage_runs",
    "stage_qa_reports",
)


def reset_storygraph_collections(repo: Repo) -> None:
    """Clear derived graph collections before a forced S1_EXTRACT re-extraction."""
    for col in _RESETTABLE_COLLECTIONS:
        for doc in repo.store.query(col):
            doc_id = doc.get("id")
            if doc_id:
                repo.store.delete(col, str(doc_id))
    repo.store.delete("meta", "style_guide")
    meta = repo.get_project_meta()
    if meta:
        repo.put_project_meta(
            meta.model_copy(
                update={
                    "status": "in_progress",
                    "current_stage": "S1_EXTRACT",
                    "final_video_uri": None,
                    "final_video_url": None,
                    "error_message": None,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

"""Runtime configuration, repository construction, and collection reset helpers."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from functools import lru_cache

from google.cloud import firestore
from storygraph.config import Config
from storygraph.pipeline import Pipeline
from storygraph.presets import resolve_production_presets
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


@lru_cache(maxsize=1)
def _base_config() -> Config:
    """Parsed `default.yaml` (~12 ms to parse + validate), loaded once per process."""
    return Config.load()


@lru_cache(maxsize=4)
def _firestore_client(gcp_project: str, database: str) -> firestore.Client:
    """One thread-safe client per process: reuses auth + the gRPC channel across requests."""
    return firestore.Client(project=gcp_project, database=database)


def load_runtime_config() -> Config:
    """Load StoryGraph configuration with Cloud Run / environment variable overrides."""
    cfg = _base_config().model_copy(deep=True)
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


def _graph_store(project_id: str, cfg: Config) -> FirestoreStore | MemoryStore:
    """The configured GraphStore for a project (shared Firestore client)."""
    if cfg.store.backend == "firestore" and cfg.store.firestore_project:
        return FirestoreStore(
            project_id=project_id,
            gcp_project=cfg.store.firestore_project,
            database=cfg.store.firestore_database,
            collection_prefix=cfg.store.collection_prefix,
            max_doc_bytes=cfg.store.max_doc_bytes,
            client=_firestore_client(
                cfg.store.firestore_project, cfg.store.firestore_database
            ),
        )
    return MemoryStore(
        project_id=project_id, max_doc_bytes=cfg.store.max_doc_bytes, shared=True
    )


def get_graph_store(project_id: str) -> FirestoreStore | MemoryStore:
    """GraphStore only (no blobs, no legacy auto-seed reads): for cheap status reads."""
    return _graph_store(project_id, load_runtime_config())


def _build_store_and_blobs(
    project_id: str, cfg: Config
) -> tuple[FirestoreStore | MemoryStore, GcsBlobStore | LocalBlobStore]:
    """Instantiate the configured GraphStore and BlobStore backends for a project."""
    store = _graph_store(project_id, cfg)
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
    base_concept = str(pdata.get("base_concept") or pdata.get("story_text") or "")
    ptype = str(pdata.get("type") or "movie")
    orient = str(pdata.get("orientation") or "16:9")
    bundle = resolve_production_presets(
        visual_style_id=str(pdata["visual_style_preset"])
        if pdata.get("visual_style_preset")
        else None,
        color_palette_id=str(pdata["color_palette_preset"])
        if pdata.get("color_palette_preset")
        else None,
        director_style_id=str(pdata["director_style_preset"])
        if pdata.get("director_style_preset")
        else None,
        screenplay_style_id=str(pdata["screenplay_style_preset"])
        if pdata.get("screenplay_style_preset")
        else None,
        music_style_id=str(pdata["music_style_preset"])
        if pdata.get("music_style_preset")
        else None,
    )
    auto_gates = pdata.get("auto_approve_gates")
    meta = ProjectMeta(
        id=project_id,
        name=str(pdata.get("name") or project_id),
        type=ptype if ptype in ("movie", "advertizement", "social") else "movie",  # type: ignore[arg-type]
        base_concept=base_concept,
        story_text=base_concept,
        video_length=str(pdata.get("video_length") or "auto"),
        orientation=orient if orient in ("16:9", "9:16") else "16:9",  # type: ignore[arg-type]
        language=str(pdata.get("language") or "en-IN"),
        visual_style_preset=bundle.visual_style.id,
        color_palette_preset=bundle.color_palette.id,
        director_style_preset=bundle.director_style.id,
        screenplay_style_preset=bundle.screenplay_style.id,
        music_style_preset=bundle.music_style.id,
        auto_approve_gates=bool(auto_gates) if auto_gates is not None else True,
    )
    return meta, base_concept


def _sync_existing_meta_from_firestore(
    repo: Repo, existing: ProjectMeta, pdata: dict[str, object]
) -> None:
    """Sync creative presets and brief metadata from `productions/{id}` into an existing `ProjectMeta`."""
    seeded, _ = _seed_meta_from_firestore_doc(existing.id, pdata)
    updates: dict[str, object] = {}
    for k in (
        "visual_style_preset",
        "color_palette_preset",
        "director_style_preset",
        "screenplay_style_preset",
        "music_style_preset",
    ):
        if pdata.get(k) and getattr(existing, k) != getattr(seeded, k):
            updates[k] = getattr(seeded, k)
    if updates:
        repo.put_project_meta(existing.model_copy(update=updates))
        sg = repo.get_style_guide()
        if sg is not None:
            repo.put_style_guide(sg.model_copy(update=updates))


def _auto_seed_firestore_project(
    repo: Repo, store: FirestoreStore, cfg: Config, project_id: str
) -> None:
    """Seed or sync StoryGraph metadata from an existing Firestore production document."""
    try:
        prod_doc = store._db.collection("productions").document(project_id).get()
        doc = prod_doc if prod_doc.exists else store._root.get()
        if not doc.exists:
            return
        pdata = doc.to_dict() or {}
        existing = repo.get_project_meta()
        if existing is None:
            meta, base_concept = _seed_meta_from_firestore_doc(project_id, pdata)
            repo.put_project_meta(meta)
            repo.put_source_text(base_concept)
            Pipeline(repo=repo, cfg=cfg).ingest_story(base_concept)
        else:
            _sync_existing_meta_from_firestore(repo, existing, pdata)
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
    if isinstance(store, FirestoreStore):
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
    "prompt_versions",
    "keyframe_sets",
    "previz_layouts",
    "previz_shots",
    "previz_runs",
)

ALL_PROJECT_COLLECTIONS: tuple[str, ...] = (
    "meta",
    *_RESETTABLE_COLLECTIONS,
    "stage_jobs",
    "audit_log",
)


def _extract_uris(obj: object, out: set[str]) -> None:
    """Recursively collect `gs://` and `file://` URIs from a serialized document dict/list."""
    if isinstance(obj, str):
        if obj.startswith(("gs://", "file://")):
            out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _extract_uris(v, out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _extract_uris(item, out)


def collect_project_blob_uris(store: FirestoreStore | MemoryStore) -> set[str]:
    """Scan asset-bearing collections for any `gs://` or `file://` URIs referenced by a project."""
    uris: set[str] = set()
    uri_collections = (
        "meta",
        "assets",
        "generation_runs",
        "keyframe_sets",
        "previz_layouts",
        "previz_shots",
    )
    for col in uri_collections:
        for row in store.query(col):
            _extract_uris(row, uris)
    return uris


def purge_storygraph_project(project_id: str) -> dict[str, int]:
    """Delete all blobs (GCS/local), StoryGraph subcollections, and root doc for `project_id`."""
    cfg = load_runtime_config()
    store, blobs = _build_store_and_blobs(project_id, cfg)
    extra_uris = collect_project_blob_uris(store)
    deleted_blobs = blobs.delete_project_blobs(extra_uris)
    deleted_docs = store.purge_project(ALL_PROJECT_COLLECTIONS)
    MEMORY_PROJECT_INDEX.discard(project_id)
    logger.info(
        "Purged StoryGraph production and assets",
        extra={
            "who": "purge_storygraph_project",
            "where": "productions_service.services.runtime",
            "what": project_id,
            "when": datetime.now(UTC).isoformat(),
            "why": "hard delete production and cleanup all assets",
            "how": f"deleted_blobs={deleted_blobs} deleted_docs={deleted_docs}",
        },
    )
    return {"deleted_blobs": deleted_blobs, "deleted_docs": deleted_docs}


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
                    "auto_approve_gates": True,
                    "final_video_uri": None,
                    "final_video_url": None,
                    "error_message": None,
                    "updated_at": datetime.now(UTC),
                }
            )
        )

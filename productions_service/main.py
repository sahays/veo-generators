"""Dedicated Cloud Run microservice (`veo-generators-productions`) for the Story-to-Video Graph System.

Serves `/api/v1/productions/*`:
- `POST /api/v1/productions`: Create a new StoryGraph production from a story idea/concept
- `GET /api/v1/productions`: List all productions
- `GET /api/v1/productions/{id}`: Full StoryGraph snapshot (plus backward-compatible `scenes`, `status`, `total_usage`)
- `PATCH /api/v1/productions/{id}`: Update project metadata
- `POST /api/v1/productions/{id}/archive` & `unarchive`: Archive / unarchive production
- `POST /api/v1/productions/{id}/run`: Run pipeline forward until next unapproved gate (or end-to-end if `auto_approve_gates=True`)
- `POST /api/v1/productions/{id}/analyze`: Alias for running `S1_EXTRACT` (or `run_until_gate_or_done`)
- `POST /api/v1/productions/{id}/render`: Alias for running forward through `S10_ASSEMBLE` (auto-approving remaining gates if requested)
- `POST /api/v1/productions/{id}/stages/{stage_id}/run`: Run a single stage (`S1_EXTRACT` .. `S10_ASSEMBLE`)
- `POST /api/v1/productions/{id}/gates/{gate_id}/approve` & `reject`: Approve or reject Gate `G1`, `G2`, or `G3`
- `POST /api/v1/productions/{id}/appearances/{appearance_id}/approve` & `regenerate`: Approve or re-run Designer agent for an Appearance
- `POST /api/v1/productions/{id}/shots/{shot_id}/compile`: Preview deterministic `RefPlan` and compiled `Package` prompt for a Shot
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from storygraph.agents.design_studio import design_single_entity
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.errors import (
    BudgetExceeded,
    GateBlocked,
    NotFound,
    PermissionDenied,
    StoryGraphError,
    ValidationFailed,
)
from storygraph.pipeline import Pipeline, Stage, approve_gate, reject_gate
from storygraph.repo import Repo
from storygraph.schema import EntityType, ProjectMeta, Status
from storygraph.store import (
    FirestoreStore,
    GcsBlobStore,
    LocalBlobStore,
    MemoryStore,
)
from storygraph.validate import validate_all
from storygraph.views import shot_view

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Veo Generators — Story-to-Video Graph Productions Service",
)

# Registry of known project IDs when running in memory mode
_MEMORY_PROJECT_INDEX: set[str] = set()


def _load_runtime_config() -> Config:
    cfg = Config.load()
    is_cloud_run = bool(os.getenv("K_SERVICE"))
    has_gcp = is_cloud_run and bool(os.getenv("GOOGLE_CLOUD_PROJECT"))
    default_store = "firestore" if has_gcp else cfg.store.backend
    default_blobs = (
        "gcs" if (is_cloud_run and os.getenv("GCS_BUCKET")) else cfg.blobs.backend
    )
    default_image = "gemini" if has_gcp else cfg.image.provider
    default_video = "gemini" if has_gcp else cfg.video.provider
    store_backend = os.getenv("STORYGRAPH_STORE_BACKEND", default_store)
    blob_backend = os.getenv("STORYGRAPH_BLOB_BACKEND", default_blobs)
    image_provider = os.getenv("STORYGRAPH_IMAGE_PROVIDER", default_image)
    video_provider = os.getenv("STORYGRAPH_VIDEO_PROVIDER", default_video)
    cfg.store.backend = store_backend
    cfg.store.firestore_project = os.getenv(
        "GOOGLE_CLOUD_PROJECT", cfg.store.firestore_project
    )
    cfg.blobs.backend = blob_backend
    cfg.blobs.gcs_bucket = os.getenv("GCS_BUCKET", cfg.blobs.gcs_bucket)
    cfg.image.provider = image_provider
    cfg.video.provider = video_provider
    if has_gcp:
        cfg.caps.shot_max_retries = 1
        cfg.caps.design_loop_max = 1
    return cfg


def get_repo(project_id: str, cfg: Config | None = None) -> Repo:
    c = cfg or _load_runtime_config()
    if c.store.backend == "firestore" and c.store.firestore_project:
        store = FirestoreStore(
            project_id=project_id,
            gcp_project=c.store.firestore_project,
            database=c.store.firestore_database,
            collection_prefix=c.store.collection_prefix,
            max_doc_bytes=c.store.max_doc_bytes,
        )
    else:
        store = MemoryStore(
            project_id=project_id,
            max_doc_bytes=c.store.max_doc_bytes,
            shared=True,
        )
    if c.blobs.backend == "gcs" and c.blobs.gcs_bucket:
        blobs = GcsBlobStore(
            bucket_name=c.blobs.gcs_bucket,
            project_id=project_id,
            prefix=c.blobs.gcs_prefix,
        )
    else:
        blobs = LocalBlobStore(root_dir=c.blobs.local_root, project_id=project_id)
    repo = Repo(store=store, blobs=blobs)

    if repo.get_project_meta() is None and isinstance(store, FirestoreStore):
        try:
            doc = store._root.get()
            if not doc.exists:
                doc = store._db.collection("productions").document(project_id).get()
            if doc.exists:
                pdata = doc.to_dict() or {}
                base_concept = str(pdata.get("base_concept") or "")
                ptype = str(pdata.get("type") or "movie")
                orient = str(pdata.get("orientation") or "16:9")
                meta = ProjectMeta(
                    id=project_id,
                    name=str(pdata.get("name") or project_id),
                    type=ptype
                    if ptype in ("movie", "advertizement", "social")
                    else "movie",  # type: ignore[arg-type]
                    base_concept=base_concept,
                    story_text=base_concept,
                    video_length=str(pdata.get("video_length") or "16"),
                    orientation=orient if orient in ("16:9", "9:16") else "16:9",  # type: ignore[arg-type]
                    language=str(pdata.get("language") or "en-IN"),
                    auto_approve_gates=bool(pdata.get("auto_approve_gates", False)),
                )
                repo.put_project_meta(meta)
                repo.put_source_text(base_concept)
                Pipeline(repo=repo, cfg=c).ingest_story(base_concept)
        except Exception as exc:
            logger.warning(
                f"Failed to auto-seed StoryGraph from Firestore {project_id}: {exc}"
            )

    return repo


def build_pipeline(project_id: str) -> Pipeline:
    cfg = _load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    return Pipeline(repo=repo, cfg=cfg)


def _format_graph_snapshot(repo: Repo, cfg: Config) -> dict[str, Any]:
    """Build a complete StoryGraph response payload with signed asset URLs and backward-compatible project fields."""
    meta = repo.get_project_meta()
    if not meta:
        raise HTTPException(
            status_code=404, detail=f"Production {repo.project_id} not found"
        )

    sign_fn = getattr(repo.blobs, "sign_url", lambda u: u)

    entities = repo.list_entities()
    characters = [
        e.model_dump(mode="json")
        for e in entities
        if e.entity_type == EntityType.CHARACTER
    ]
    locations = [
        e.model_dump(mode="json")
        for e in entities
        if e.entity_type == EntityType.LOCATION
    ]
    objects = [
        e.model_dump(mode="json")
        for e in entities
        if e.entity_type == EntityType.OBJECT
    ]

    assets_raw = repo.list_assets()
    assets_by_id: dict[str, dict[str, Any]] = {}
    assets_out: list[dict[str, Any]] = []
    for a in assets_raw:
        ad = a.model_dump(mode="json")
        ad["signed_url"] = sign_fn(a.uri) if a.uri else None
        assets_by_id[a.id] = ad
        assets_out.append(ad)

    appearances_out: list[dict[str, Any]] = []
    for app_node in repo.list_appearances(active_only=False):
        apd = app_node.model_dump(mode="json")
        apd["assets"] = [
            assets_by_id[aid] for aid in app_node.asset_ids if aid in assets_by_id
        ]
        appearances_out.append(apd)

    events_out = [e.model_dump(mode="json") for e in repo.list_events()]
    state_facts_out = [sf.model_dump(mode="json") for sf in repo.list_state_facts()]
    dialogue_out = [d.model_dump(mode="json") for d in repo.list_dialogue()]
    music_cues_out = [m.model_dump(mode="json") for m in repo.list_music_cues()]
    runs_out: list[dict[str, Any]] = []
    latest_run_by_shot: dict[str, dict[str, Any]] = {}
    for r in repo.list_generation_runs():
        rd = r.model_dump(mode="json")
        if r.output_video_uri:
            rd["output_video_signed_url"] = sign_fn(r.output_video_uri)
        runs_out.append(rd)
        latest_run_by_shot[r.shot_id] = rd

    shots_out: list[dict[str, Any]] = []
    for sh in repo.list_shots():
        shd = sh.model_dump(mode="json")
        shd["latest_run"] = latest_run_by_shot.get(sh.id)
        shots_out.append(shd)

    scenes_raw = repo.list_scenes()
    scenes_out: list[dict[str, Any]] = []
    legacy_scenes: list[dict[str, Any]] = []
    t_cursor = 0
    for sc in scenes_raw:
        scd = sc.model_dump(mode="json")
        scenes_out.append(scd)
        sc_shots = [s for s in shots_out if s["scene_id"] == sc.id]
        dur = int(sum(float(s.get("duration_s", 4.0)) for s in sc_shots)) or 8
        loc_apps = [
            a
            for a in appearances_out
            if a["entity_id"] == sc.location_id and a.get("assets")
        ]
        thumb_url = (
            loc_apps[-1]["assets"][-1].get("signed_url")
            if loc_apps and loc_apps[-1].get("assets")
            else None
        )
        video_url = (
            sc_shots[0]["latest_run"].get("output_video_signed_url")
            if sc_shots and sc_shots[0].get("latest_run")
            else None
        )
        legacy_scenes.append(
            {
                "id": sc.id,
                "visual_description": sc.summary
                or f"{sc.heading} ({sc.time_of_day}, {sc.weather})",
                "narration": "",
                "music_description": sc.mood,
                "timestamp_start": f"0:{t_cursor:02d}",
                "timestamp_end": f"0:{t_cursor + dur:02d}",
                "thumbnail_url": thumb_url,
                "video_url": video_url,
                "metadata": {
                    "location": sc.location_id,
                    "mood": sc.mood,
                },
            }
        )
        t_cursor += dur

    stage_runs = repo.list_stage_runs()
    tokens_in = sum(sr.tokens_in for sr in stage_runs)
    tokens_out = sum(sr.tokens_out for sr in stage_runs)
    cost_usd = round(sum(sr.cost_usd for sr in stage_runs), 4)
    image_count = sum(
        1
        for a in assets_raw
        if a.kind in ("character_sheet", "location_plate", "prop_sheet")
    )
    veo_videos = len(runs_out)
    veo_seconds = (
        sum(float(s.get("duration_s", 0.0)) for s in shots_out) if runs_out else 0.0
    )

    gates_out = [g.model_dump(mode="json") for g in repo.list_gates()]
    issues_out = [i.to_dict() for i in validate_all(repo, cfg)]
    crs_out = [
        cr.model_dump(mode="json") for cr in repo.list_change_requests(open_only=False)
    ]
    audit_out = [
        ae.model_dump(mode="json") for ae in repo.list_audit_entries(limit=150)
    ]
    sg = repo.get_style_guide()

    created_ms = int(meta.created_at.timestamp() * 1000)
    updated_ms = int(meta.updated_at.timestamp() * 1000)
    final_signed = (
        sign_fn(meta.final_video_uri) if meta.final_video_uri else meta.final_video_url
    )

    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.type,
        "base_concept": meta.base_concept,
        "story_text": repo.get_source_text() or meta.base_concept,
        "video_length": meta.video_length,
        "orientation": meta.orientation,
        "language": meta.language,
        "auto_approve_gates": meta.auto_approve_gates,
        "status": meta.status,
        "current_stage": meta.current_stage,
        "final_video_uri": meta.final_video_uri,
        "final_video_url": final_signed,
        "archived": meta.archived,
        "error_message": meta.error_message,
        "createdAt": created_ms,
        "updatedAt": updated_ms,
        "scenes": legacy_scenes,
        "total_usage": {
            "input_tokens": tokens_in,
            "output_tokens": tokens_out,
            "model_name": cfg.models.story_architect,
            "cost_usd": cost_usd,
            "image_generations": image_count,
            "image_cost_usd": round(image_count * 0.02, 4),
            "veo_videos": veo_videos,
            "veo_seconds": veo_seconds,
            "veo_unit_cost": 0.15,
            "veo_cost_usd": round(veo_seconds * 0.15, 4),
        },
        "story_graph": {
            "style_guide": sg.model_dump(mode="json") if sg else None,
            "entities": {
                "characters": characters,
                "locations": locations,
                "objects": objects,
                "all": [e.model_dump(mode="json") for e in entities],
            },
            "events": events_out,
            "state_facts": state_facts_out,
            "appearances": appearances_out,
            "assets": assets_out,
            "scenes": scenes_out,
            "dialogue_lines": dialogue_out,
            "music_cues": music_cues_out,
            "shots": shots_out,
            "generation_runs": runs_out,
            "gates": gates_out,
            "stage_runs": [sr.model_dump(mode="json") for sr in stage_runs],
            "validation_issues": issues_out,
            "change_requests": crs_out,
            "audit_log": audit_out,
        },
    }


class CreateProductionPayload(BaseModel):
    id: str | None = None
    name: str
    type: str = "movie"
    base_concept: str
    story_text: str | None = None
    video_length: str = "16"
    orientation: str = "16:9"
    language: str = "en-IN"
    auto_approve_gates: bool = False
    reference_image_url: str | None = None
    prompt_id: str | None = None


class RunPipelinePayload(BaseModel):
    auto_approve_gates: bool | None = None
    story_text: str | None = None


class GateDecisionPayload(BaseModel):
    reviewer: str = "studio_user"
    notes: str | None = None


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "veo-generators-productions",
        "engine": "storygraph-v1",
    }


@app.post("/api/v1/productions")
async def create_production(body: CreateProductionPayload, request: Request):
    project_id = body.id or f"prod_{uuid.uuid4().hex[:10]}"
    cfg = _load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    invite_code = request.headers.get("X-Invite-Code", "")

    ptype = body.type if body.type in ("movie", "advertizement", "social") else "movie"
    orient = body.orientation if body.orientation in ("16:9", "9:16") else "16:9"
    story = (body.story_text or body.base_concept).strip()

    meta = ProjectMeta(
        id=project_id,
        name=body.name,
        type=ptype,  # type: ignore[arg-type]
        base_concept=body.base_concept,
        story_text=story,
        video_length=str(body.video_length),
        orientation=orient,  # type: ignore[arg-type]
        language=body.language,
        auto_approve_gates=body.auto_approve_gates,
        status="draft",
        current_stage="S0_INGEST",
        invite_code=invite_code or None,
    )
    repo.put_project_meta(meta)
    repo.put_source_text(story)
    _MEMORY_PROJECT_INDEX.add(project_id)

    pipe = Pipeline(repo=repo, cfg=cfg)
    pipe.ingest_story(story)
    return _format_graph_snapshot(repo, cfg)


@app.get("/api/v1/productions")
async def list_productions(archived: bool = False):
    cfg = _load_runtime_config()
    results: list[dict[str, Any]] = []
    for pid in sorted(_MEMORY_PROJECT_INDEX):
        repo = get_repo(pid, cfg=cfg)
        meta = repo.get_project_meta()
        if not meta:
            continue
        if not archived and meta.archived:
            continue
        results.append(_format_graph_snapshot(repo, cfg))
    results.sort(key=lambda r: r.get("updatedAt", 0), reverse=True)
    return results


@app.get("/api/v1/productions/{project_id}")
@app.get("/api/v1/productions/{project_id}/graph")
async def get_production(project_id: str):
    cfg = _load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    return _format_graph_snapshot(repo, cfg)


@app.patch("/api/v1/productions/{project_id}")
async def update_production(project_id: str, updates: dict[str, Any]):
    cfg = _load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    meta = repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")

    allowed_fields = {
        "name",
        "type",
        "base_concept",
        "story_text",
        "video_length",
        "orientation",
        "language",
        "auto_approve_gates",
        "status",
        "archived",
    }
    patch_dict = {
        k: v for k, v in updates.items() if k in allowed_fields and v is not None
    }
    patch_dict["updated_at"] = datetime.now(UTC)
    updated_meta = meta.model_copy(update=patch_dict)
    repo.put_project_meta(updated_meta)
    if "base_concept" in patch_dict or "story_text" in patch_dict:
        repo.put_source_text(
            str(patch_dict.get("story_text") or patch_dict.get("base_concept"))
        )
    return _format_graph_snapshot(repo, cfg)


@app.post("/api/v1/productions/{project_id}/archive")
async def archive_production(project_id: str):
    return await update_production(project_id, {"archived": True})


@app.post("/api/v1/productions/{project_id}/unarchive")
async def unarchive_production(project_id: str):
    return await update_production(project_id, {"archived": False})


@app.post("/api/v1/productions/{project_id}/run")
async def run_production_pipeline(
    project_id: str,
    body: RunPipelinePayload | None = None,
):
    pipe = build_pipeline(project_id)
    meta = pipe.repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")

    auto_approve = body.auto_approve_gates if body else None
    story_text = body.story_text if body else None
    blocked_gate: str | None = None

    try:
        pipe.run_until_gate_or_done(
            story_text=story_text,
            auto_approve_gates=auto_approve,
        )
    except GateBlocked as gb:
        blocked_gate = gb.gate_id
        current_meta = pipe.repo.get_project_meta() or meta
        pipe.repo.put_project_meta(
            current_meta.model_copy(
                update={
                    "status": f"awaiting_{gb.gate_id.lower()}",
                    "updated_at": datetime.now(UTC),
                }
            )
        )
    except (ValidationFailed, BudgetExceeded, PermissionDenied, StoryGraphError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    snap = _format_graph_snapshot(pipe.repo, pipe.cfg)
    snap["blocked_gate"] = blocked_gate
    return snap


@app.post("/api/v1/productions/{project_id}/analyze")
async def analyze_production_compat(
    project_id: str,
    body: dict[str, Any] | None = None,
):
    """Compatibility endpoint for triggering initial story expansion & world extraction."""
    payload = body or {}
    if payload:
        await update_production(project_id, payload)
    snap = await run_production_pipeline(
        project_id,
        RunPipelinePayload(
            auto_approve_gates=payload.get("auto_approve_gates"),
            story_text=payload.get("base_concept"),
        ),
    )
    return {
        "data": {
            "scenes": snap["scenes"],
            "story_graph": snap["story_graph"],
        },
        "usage": snap["total_usage"],
        "production": snap,
    }


@app.post("/api/v1/productions/{project_id}/render")
async def render_production_compat(
    project_id: str,
    body: dict[str, Any] | None = None,
):
    """Run the production forward (optionally auto-approving gates if requested)."""
    auto_approve = (body or {}).get("auto_approve_gates", True)
    return await run_production_pipeline(
        project_id, RunPipelinePayload(auto_approve_gates=auto_approve)
    )


def _reset_storygraph_collections(repo: Repo) -> None:
    """Clear derived graph collections before a forced S1_EXTRACT re-extraction."""
    cols = (
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
    )
    for col in cols:
        for doc in repo.store.query(col):
            doc_id = doc.get("id")
            if doc_id:
                repo.store.delete(col, str(doc_id))


@app.post("/api/v1/productions/{project_id}/stages/{stage_id}/run")
async def run_single_stage(
    project_id: str,
    stage_id: str,
    force: bool = True,
):
    pipe = build_pipeline(project_id)
    meta = pipe.repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")
    try:
        st = Stage(stage_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown stage '{stage_id}'")

    try:
        if st == Stage.S1_EXTRACT and force:
            _reset_storygraph_collections(pipe.repo)
            pipe.run_stage(Stage.S1_EXTRACT, force=True)
        elif st == Stage.S8_RENDER and force:
            for sh in pipe.repo.list_shots():
                pipe.repo.put_shot(
                    sh.model_copy(
                        update={
                            "stale": True,
                            "stale_reason": "Manual re-render requested",
                        }
                    )
                )
            pipe.run_stage(Stage.S8_RENDER, force=True)
            pipe.run_stage(Stage.S9_QA, force=True)
            pipe.run_stage(Stage.S10_ASSEMBLE, force=True)
        else:
            pipe.run_stage(st, force=force)
    except GateBlocked as gb:
        raise HTTPException(
            status_code=409,
            detail=f"Stage {stage_id} blocked by unapproved gate {gb.gate_id}",
        )
    except (ValidationFailed, BudgetExceeded, PermissionDenied, StoryGraphError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _format_graph_snapshot(pipe.repo, pipe.cfg)


@app.post("/api/v1/productions/{project_id}/gates/{gate_id}/approve")
async def approve_production_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
    advance: bool = True,
):
    if gate_id not in ("G1", "G2", "G3"):
        raise HTTPException(status_code=400, detail=f"Invalid gate_id '{gate_id}'")
    pipe = build_pipeline(project_id)
    meta = pipe.repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")

    decision = body or GateDecisionPayload()
    approve_gate(
        pipe.repo,
        gate_id=gate_id,  # type: ignore[arg-type]
        reviewer=decision.reviewer,
        notes=decision.notes,
    )
    if advance:
        return await run_production_pipeline(project_id)
    return _format_graph_snapshot(pipe.repo, pipe.cfg)


@app.post("/api/v1/productions/{project_id}/gates/{gate_id}/reject")
async def reject_production_gate(
    project_id: str,
    gate_id: str,
    body: GateDecisionPayload | None = None,
):
    if gate_id not in ("G1", "G2", "G3"):
        raise HTTPException(status_code=400, detail=f"Invalid gate_id '{gate_id}'")
    pipe = build_pipeline(project_id)
    meta = pipe.repo.get_project_meta()
    if not meta:
        raise HTTPException(status_code=404, detail="Production not found")

    decision = body or GateDecisionPayload()
    reject_gate(
        pipe.repo,
        gate_id=gate_id,  # type: ignore[arg-type]
        reviewer=decision.reviewer,
        notes=decision.notes or "Revision requested",
    )
    return _format_graph_snapshot(pipe.repo, pipe.cfg)


@app.post("/api/v1/productions/{project_id}/appearances/{appearance_id}/approve")
async def approve_single_appearance(project_id: str, appearance_id: str):
    cfg = _load_runtime_config()
    repo = get_repo(project_id, cfg=cfg)
    app_node = repo.get_appearance(appearance_id)
    if not app_node:
        raise HTTPException(
            status_code=404, detail=f"Appearance {appearance_id} not found"
        )
    repo.update_appearance_status(appearance_id, Status.APPROVED)
    for aid in app_node.asset_ids:
        repo.update_asset(aid, status=Status.APPROVED)
    return _format_graph_snapshot(repo, cfg)


@app.post("/api/v1/productions/{project_id}/appearances/{appearance_id}/regenerate")
async def regenerate_single_appearance(project_id: str, appearance_id: str):
    pipe = build_pipeline(project_id)
    app_node = pipe.repo.get_appearance(appearance_id)
    if not app_node:
        raise HTTPException(
            status_code=404, detail=f"Appearance {appearance_id} not found"
        )
    design_single_entity(
        pipe.repo,
        pipe.cfg,
        entity_id=app_node.entity_id,
        image_gen=pipe.image_gen,
        vlm=pipe.vlm,
        force_regenerate=True,
    )
    return _format_graph_snapshot(pipe.repo, pipe.cfg)


@app.post("/api/v1/productions/{project_id}/shots/{shot_id}/compile")
async def compile_single_shot_preview(project_id: str, shot_id: str):
    pipe = build_pipeline(project_id)
    try:
        sv = shot_view(pipe.repo, shot_id)
        plan = select_references(sv, pipe.cfg, caps=pipe.video_gen.caps, repo=pipe.repo)
        pkg = compile_shot(
            sv,
            plan,
            pipe.cfg,
            caps=pipe.video_gen.caps,
            project_id=project_id,
            attempt=1,
        )
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf))
    except StoryGraphError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "shot_id": pkg.shot_id,
        "compiled_prompt": pkg.compiled_prompt,
        "negative_prompt": pkg.negative_prompt,
        "reference_asset_ids": pkg.reference_asset_ids,
        "first_frame_asset_id": pkg.first_frame_asset_id,
        "dropped_to_verbal": pkg.dropped_to_verbal,
        "candidate_scores": plan.candidate_scores,
        "duration_s": pkg.duration_s,
        "aspect_ratio": pkg.aspect_ratio,
        "seed": pkg.seed,
        "package_hash": pkg.package_hash,
    }

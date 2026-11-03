"""Blender previz tab: board, background S8_PREVIZ runs and variant promotion (thin service).

All heavy work runs in `storygraph.previz` (stage / promote); this module validates input,
starts the background run and maps stored records to the typed HTTP contract
(`previz_contract.py`). Only media that exist are returned, as signed URLs.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import HTTPException

from storygraph.errors import NotFound, StoryGraphError, ValidationFailed
from storygraph.previz.factory import blender_version, build_previz_deps
from storygraph.previz.stage.promote import promote_variant
from storygraph.previz.stage.stage import run_previz
from storygraph.repo import Repo
from storygraph.repo.previz_layouts import PrevizLayoutRepo
from storygraph.repo.previz_shots import PrevizRunRepo, PrevizShotRepo
from storygraph.schema import Role, Shot
from storygraph.schemas.previz import PrevizLayout, PrevizRun, PrevizShot
from storygraph.store.url_signing import sign_many

from .previz_contract import (
    ID_PATTERN,
    PrevizBoardResponse,
    PrevizLayoutView,
    PrevizRunAccepted,
    PrevizRunPayload,
    PrevizStageRunView,
    PrevizVariantView,
    PromotePrevizPayload,
    ShotPreviz,
)
from .runtime import build_pipeline, get_repo, load_runtime_config

logger = logging.getLogger(__name__)


def _log(what: str, why: str, project_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.previz_service",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "storygraph.previz (S8_PREVIZ, background thread)",
            "project_id": project_id,
            **extra,
        },
    )


def _check_id(value: str, what: str) -> str:
    if not re.fullmatch(ID_PATTERN, value):
        raise HTTPException(status_code=400, detail=f"invalid {what}")
    return value


def _repo(project_id: str) -> Repo:
    repo = get_repo(_check_id(project_id, "project id"), cfg=load_runtime_config())
    if not repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    return repo


def _signed(repo: Repo, uris: list[str]) -> dict[str, str]:
    """`uri -> signed URL` for URIs whose media exist (bounded-parallel, cached signer)."""
    blobs = repo.blobs
    exists = getattr(blobs, "exists", None)

    def sign_present(uri: str) -> str:
        present = exists(uri) if callable(exists) else True
        return blobs.sign_url(uri) if present else ""

    return {u: url for u, url in sign_many(sign_present, uris).items() if url}


def _record_uris(records: list[PrevizShot], layouts: list[PrevizLayout]) -> list[str]:
    uris = [pl.thumbnail_uri for pl in layouts if pl.thumbnail_uri]
    for ps in records:
        uris += [ps.previz_video_uri] if ps.previz_video_uri else []
        for v in ps.variants:
            uris += ([v.video_uri] if v.video_uri else []) + list(v.frame_uris)
    return uris


def _shot_view(shot: Shot, ps: PrevizShot | None, urls: dict[str, str]) -> ShotPreviz:
    base = ShotPreviz(
        shot_id=shot.id, scene_id=shot.scene_id, clip_index=shot.clip_index or 0
    )
    if ps is None:
        return base
    variants = [
        PrevizVariantView(
            variant=v.variant,
            status=v.status,
            video_url=urls.get(v.video_uri or ""),
            frame_urls=[urls[u] for u in v.frame_uris if u in urls],
            failure_reason=v.failure_reason,
            promoted=v.promoted,
        )
        for v in ps.variants
    ]
    return base.model_copy(
        update={
            "status": ps.previz_status,
            "failure_reason": ps.failure_reason,
            "previz_video_url": urls.get(ps.previz_video_uri or ""),
            "render_seconds": ps.render_seconds,
            "variants": variants,
        }
    )


def _stage_view(run: PrevizRun | None) -> PrevizStageRunView | None:
    if run is None:
        return None
    return PrevizStageRunView(
        status=run.run_status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
    )


def _layout_views(
    layouts: list[PrevizLayout], urls: dict[str, str]
) -> list[PrevizLayoutView]:
    return [
        PrevizLayoutView(
            location_id=pl.location_id,
            name=pl.layout.name,
            version=pl.version,
            thumbnail_url=urls.get(pl.thumbnail_uri or ""),
        )
        for pl in layouts
    ]


@lru_cache(maxsize=1)
def _blender_version() -> str | None:
    return blender_version()


def get_previz_board(project_id: str) -> dict[str, Any]:
    repo = _repo(project_id)
    records = PrevizShotRepo(repo.store).active_by_shot()
    layouts = PrevizLayoutRepo(repo.store).list_active()
    urls = _signed(repo, _record_uris(list(records.values()), layouts))
    shots = sorted(
        (s for s in repo.list_shots() if s.clip_index is not None),
        key=lambda s: (s.scene_id, s.clip_index or 0),
    )
    board = PrevizBoardResponse(
        project_id=project_id,
        blender_version=_blender_version(),
        stage_run=_stage_view(PrevizRunRepo(repo.store).latest()),
        layouts=_layout_views(layouts, urls),
        shots=[_shot_view(s, records.get(s.id), urls) for s in shots],
    )
    return board.model_dump(mode="json")


def _validated_scenes(repo: Repo, body: PrevizRunPayload) -> list[str] | None:
    if body.scene_ids is None:
        return None
    known = {s.id for s in repo.list_scenes()}
    unknown = [s for s in body.scene_ids if s not in known]
    if unknown:
        raise HTTPException(
            status_code=404, detail=f"unknown scene id(s): {unknown[:5]}"
        )
    return list(dict.fromkeys(body.scene_ids))


def _background(project_id: str, run: PrevizRun) -> None:
    """Thread body: build adapters, execute the run; the run record is always closed."""
    pipe = build_pipeline(project_id)
    try:
        deps = build_previz_deps(
            pipe.repo, pipe.cfg, pipe.image_gen, pipe.vlm, pipe.video_gen
        )
    except (StoryGraphError, OSError, ValueError) as exc:
        failed = run.model_copy(
            update={
                "run_status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "error": f"previz setup failed: {exc}"[:400],
            }
        )
        PrevizRunRepo(pipe.repo.store).put(failed)
        return
    run_previz(deps, run)


def _spawn(project_id: str, run: PrevizRun) -> None:
    """Start the background thread executing `run` (patched in tests)."""
    threading.Thread(
        target=_background, args=(project_id, run), name=f"previz-{run.id}", daemon=True
    ).start()


STALE_RUN_S = 2 * 3600  # a "running" record older than this died with its instance


def _live_runs(runs: PrevizRunRepo) -> list[PrevizRun]:
    now = datetime.now(UTC)
    return [
        r
        for r in runs.running()
        if (now - datetime.fromisoformat(r.started_at)).total_seconds() < STALE_RUN_S
    ]


def start_previz_run(project_id: str, body: PrevizRunPayload) -> dict[str, Any]:
    repo = _repo(project_id)
    runs = PrevizRunRepo(repo.store)
    if _live_runs(runs):
        raise HTTPException(
            status_code=409, detail="a previz run is already in progress"
        )
    run = runs.put(
        PrevizRun(
            id=f"pzr_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}",
            created_by=Role.HUMAN,
            variant=body.variant,
            scene_ids=_validated_scenes(repo, body),
            force=body.force,
            started_at=datetime.now(UTC).isoformat(),
        )
    )
    _spawn(project_id, run)
    _log(
        "previz run started", f"variant={body.variant}", project_id, stage_run_id=run.id
    )
    return PrevizRunAccepted(stage_run_id=run.id).model_dump(mode="json")


def promote_shot_previz(
    project_id: str, shot_id: str, body: PromotePrevizPayload
) -> dict[str, Any]:
    repo = _repo(project_id)
    shot = repo.get_shot(_check_id(shot_id, "shot id"))
    if shot is None:
        raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found")
    try:
        ps = promote_variant(repo, shot.id, body.variant)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _log(
        "previz variant promoted",
        f"variant={body.variant}",
        project_id,
        shot_id=shot.id,
    )
    urls = _signed(repo, _record_uris([ps], []))
    return _shot_view(shot, ps, urls).model_dump(mode="json")


PREVIZ_STAGE_ID = "S8_PREVIZ"


def retry_last_previz(project_id: str) -> dict[str, Any]:
    """Generic stage-runner retry: repeat the last S8_PREVIZ request (force=false)."""
    repo = _repo(project_id)
    last = PrevizRunRepo(repo.store).latest()
    body = PrevizRunPayload(
        variant=last.variant if last else "previz_only",
        scene_ids=last.scene_ids if last else None,
        force=False,
    )
    return start_previz_run(project_id, body)

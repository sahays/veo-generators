"""S8_KEYFRAMES endpoints: the per-shot keyframe strip and per-frame regenerate/edit.

Contract: `services/keyframes_contract.py` (mirrored by `frontend/src/lib/api/keyframes.ts`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from storygraph.errors import NotFound, StoryGraphError, ValidationFailed
from storygraph.keyframes.stage.regenerate import regenerate_from
from storygraph.keyframes.stage.scene_plans import stored_scene_plans
from storygraph.pipeline.keyframes.stage_adapter import keyframe_deps
from storygraph.repo import Repo
from storygraph.repo.keyframe_sets import KeyframeSetRepo
from storygraph.schema import Shot

from .keyframes_contract import (
    KeyframeBoardResponse,
    KeyframeFrameView,
    KeyframeSetVersionView,
    KeyframeStripResponse,
    RegenerateKeyframePayload,
)
from .runtime import build_pipeline, get_repo, load_runtime_config

__all__ = ["get_keyframe_board", "get_shot_keyframes", "regenerate_shot_keyframe"]
logger = logging.getLogger(__name__)


def _log(what: str, why: str, project_id: str, shot_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.keyframes_service",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "KeyframeSetRepo / keyframes.stage.regenerate",
            "project_id": project_id,
            "shot_id": shot_id,
            **extra,
        },
    )


def _repo(project_id: str) -> Repo:
    repo = get_repo(project_id, cfg=load_runtime_config())
    if not repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    return repo


def _current_hashes(repo: Repo, scene_ids: set[str]) -> dict[str, str]:
    """`shot id -> current plan hash` (one scene-level planning pass per scene)."""
    out: dict[str, str] = {}
    for scene_id in sorted(scene_ids):
        scene = repo.get_scene(scene_id)
        if scene is None:
            continue
        try:
            plans = stored_scene_plans(repo, scene)
        except ValueError:
            continue
        out |= {sid: sp.plan.plan_hash for sid, sp in plans.items()}
    return out


def _strip(
    repo: Repo, shot: Shot, sets: KeyframeSetRepo, current: dict[str, str]
) -> KeyframeStripResponse:
    versions = sets.list_for_shot(shot.id)
    active = next((v for v in reversed(versions) if v.set_status == "active"), None)
    base = KeyframeStripResponse(
        shot_id=shot.id, scene_id=shot.scene_id, clip_index=shot.clip_index or 0
    )
    history = [
        KeyframeSetVersionView(
            set_id=v.id, version=v.version, status=v.set_status,
            created_at=v.created_at.isoformat(), reason=v.reason,
        )
        for v in versions
    ]  # fmt: skip
    if active is None:
        return base.model_copy(update={"versions": history})
    frames = [
        KeyframeFrameView(
            **f.model_dump(exclude={"uri"}), url=repo.blobs.sign_url(f.uri)
        )
        for f in active.frames
    ]
    return base.model_copy(
        update={
            "set_id": active.id,
            "version": active.version,
            "plan_hash": active.plan_hash,
            "needs_manual_edit": active.needs_manual_edit,
            "stale": current.get(shot.id) != active.plan_hash,
            "failure_reason": active.failure_reason,
            "frames": frames,
            "versions": history,
        }
    )


def get_shot_keyframes(project_id: str, shot_id: str) -> dict[str, Any]:
    repo = _repo(project_id)
    shot = repo.get_shot(shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found")
    current = _current_hashes(repo, {shot.scene_id})
    return _strip(repo, shot, KeyframeSetRepo(repo.store), current).model_dump(
        mode="json"
    )


def get_keyframe_board(project_id: str) -> dict[str, Any]:
    repo = _repo(project_id)
    sets = KeyframeSetRepo(repo.store)
    shots = sorted(repo.list_shots(), key=lambda s: (s.scene_id, s.clip_index or 0))
    current = _current_hashes(repo, {s.scene_id for s in shots})
    board = KeyframeBoardResponse(
        project_id=project_id,
        strategy=load_runtime_config().video.render_strategy,
        shots=[
            _strip(repo, s, sets, current) for s in shots if s.clip_index is not None
        ],
    )
    return board.model_dump(mode="json")


def regenerate_shot_keyframe(
    project_id: str, shot_id: str, t: int, body: RegenerateKeyframePayload | None
) -> dict[str, Any]:
    """Re-derive frames t..N of the shot (+ later clips of the scene); render goes stale."""
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    instruction = body.instruction if body else ""
    deps = keyframe_deps(pipe.repo, pipe.cfg, pipe.image_gen, pipe.vlm)
    try:
        ks = regenerate_from(deps, shot_id, t, instruction)
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf)) from nf
    except (ValidationFailed, StoryGraphError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _log("keyframe_regenerated", instruction or "user regenerate", project_id, shot_id,
         t=t, keyframe_set_id=ks.id, needs_manual_edit=ks.needs_manual_edit)  # fmt: skip
    return get_shot_keyframes(project_id, shot_id)

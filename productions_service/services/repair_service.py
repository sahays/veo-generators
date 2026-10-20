"""Shot repair endpoints: auto-repair blocking shots, manual clip edit, single-shot regenerate."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from storygraph.assembly import evaluate_shot_readiness
from storygraph.errors import NotFound, StoryGraphError, ValidationFailed
from storygraph.pipeline import Pipeline, Stage
from storygraph.repair import RepairReport
from storygraph.repair.clip_edit import ClipEdit, edit_shot_clip
from storygraph.repair.loop import regenerate_shot, repair_failed_shots
from storygraph.schema import Role, StageRun, Status

from .runtime import build_pipeline
from .snapshot import format_graph_snapshot

__all__ = [
    "ClipEdit",
    "RepairShotsPayload",
    "edit_project_shot_clip",
    "regenerate_project_shot",
    "repair_project_shots",
]
logger = logging.getLogger(__name__)
REPAIR_STAGE = "S8_REPAIR"


class RepairShotsPayload(BaseModel):
    """Optional subset of blocking shots to repair (default: all blocking, non-flagged)."""

    shot_ids: list[str] | None = None


def _log(what: str, why: str, how: str, project_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.repair_service",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            "project_id": project_id,
            **extra,
        },
    )


def _pipe(project_id: str) -> Pipeline:
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    return pipe


def _record(pipe: Pipeline, input_hash: str, done: bool, error: str | None) -> None:
    """Append an `S8_REPAIR` StageRun (start: completed=False; end: completed/error)."""
    status = Status.FAILED if error else (Status.APPROVED if done else Status.DRAFT)
    pipe.repo.record_stage_run(
        StageRun(
            id=f"sr_{REPAIR_STAGE}_{uuid.uuid4().hex[:8]}",
            created_by=Role.PIPELINE,
            status=status,
            stage=REPAIR_STAGE,
            input_hash=input_hash,
            completed=done and error is None,
            error=error,
        )
    )


def _tracked(
    pipe: Pipeline, label: str, run: Callable[[], RepairReport]
) -> RepairReport:
    """Run a repair callable between start/end `S8_REPAIR` StageRun records."""
    _record(pipe, label, False, None)
    try:
        report = run()
    except (KeyError, StoryGraphError) as exc:
        _record(pipe, label, False, str(exc))
        _log("shot_repair_failed", str(exc), label, pipe.repo.project_id)
        raise HTTPException(status_code=422, detail=str(exc))
    _record(pipe, label, True, None)
    return report


def _assemble_if_complete(pipe: Pipeline) -> bool:
    """Run strict S10 when every shot is ready; never raises (assembly is best-effort here)."""
    if not evaluate_shot_readiness(pipe.repo).is_complete:
        return False
    try:
        pipe.run_stage(Stage.S10_ASSEMBLE, force=True)
    except StoryGraphError as exc:
        _log(
            "post_repair_assembly_skipped", str(exc), "strict S10", pipe.repo.project_id
        )
        return False
    return True


def _response(pipe: Pipeline, report: RepairReport, assembled: bool) -> dict[str, Any]:
    snap = format_graph_snapshot(pipe.repo, pipe.cfg)
    snap["repair_report"] = report.to_payload()
    snap["assembled"] = assembled
    return snap


def repair_project_shots(
    project_id: str, body: RepairShotsPayload | None = None
) -> dict[str, Any]:
    """Repair blocking non-flagged shots, then strict-assemble if everything is ready."""
    pipe = _pipe(project_id)
    ids = body.shot_ids if body else None
    label = f"repair:{','.join(sorted(ids)) if ids else 'all_blocking'}"
    report = _tracked(
        pipe,
        label,
        lambda: repair_failed_shots(pipe.repo, pipe.cfg, pipe.video_gen, pipe.vlm, ids),
    )
    assembled = _assemble_if_complete(pipe)
    _log(
        "shot_repair_completed",
        label,
        f"assembled={assembled}",
        project_id,
        approved=report.approved,
        flagged=report.flagged,
        renders=report.total_renders,
        routes={o.shot_id: o.routes for o in report.outcomes if o.routes},
    )
    return _response(pipe, report, assembled)


def regenerate_project_shot(project_id: str, shot_id: str) -> dict[str, Any]:
    """Re-render one shot (+ continuity followers) with render + QA + repairs."""
    pipe = _pipe(project_id)
    if pipe.repo.get_shot(shot_id) is None:
        raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found")
    report = _tracked(
        pipe,
        f"regenerate:{shot_id}",
        lambda: regenerate_shot(pipe.repo, pipe.cfg, pipe.video_gen, pipe.vlm, shot_id),
    )
    return _response(pipe, report, False)


def edit_project_shot_clip(
    project_id: str, shot_id: str, body: ClipEdit
) -> dict[str, Any]:
    """Patch the shot's clip prompt / step actions; 422 `{issues:[{code,message}]}` if invalid."""
    pipe = _pipe(project_id)
    try:
        edit_shot_clip(pipe.repo, shot_id, body)
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf))
    except ValidationFailed as vf:
        issues = [
            {"code": getattr(i, "code", ""), "message": getattr(i, "message", str(i))}
            for i in vf.issues
        ]
        raise HTTPException(status_code=422, detail={"issues": issues})
    return format_graph_snapshot(pipe.repo, pipe.cfg)

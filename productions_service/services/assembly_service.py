"""Final-assembly endpoints: readiness report and manual (strict / approved-only) stitching."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from storygraph.assembly import evaluate_shot_readiness
from storygraph.errors import GateBlocked, StoryGraphError
from storygraph.pipeline import Pipeline, Stage

from .runtime import build_pipeline, get_repo, load_runtime_config
from .snapshot import format_graph_snapshot

logger = logging.getLogger(__name__)

AssembleMode = Literal["approved_only", "strict"]


def get_assembly_readiness(project_id: str) -> dict[str, Any]:
    """Return the `AssemblyReadiness` report (ready vs blocking shots) for `project_id`."""
    repo = get_repo(project_id, cfg=load_runtime_config())
    if not repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    return evaluate_shot_readiness(repo).model_dump(mode="json")


def _run_assembly(pipe: Pipeline, mode: AssembleMode) -> None:
    if mode == "approved_only":
        pipe.assemble_approved_only()
    else:
        pipe.run_stage(Stage.S10_ASSEMBLE, force=True)


def assemble_project(project_id: str, mode: AssembleMode) -> dict[str, Any]:
    """Run S10 in `mode` and return the refreshed production snapshot."""
    pipe = build_pipeline(project_id)
    if not pipe.repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    log_ctx: dict[str, Any] = {
        "who": "productions_service",
        "where": "services.assembly_service.assemble_project",
        "what": "manual_assembly",
        "when": datetime.now(UTC).isoformat(),
        "why": "user requested final video stitch",
        "how": f"mode={mode}",
        "project_id": project_id,
    }
    try:
        _run_assembly(pipe, mode)
    except GateBlocked as gb:
        raise HTTPException(
            status_code=409, detail=f"Assembly blocked by unapproved gate {gb.gate_id}"
        )
    except StoryGraphError as exc:
        logger.warning("Manual assembly rejected", extra={**log_ctx, "error": str(exc)})
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("Manual assembly completed", extra=log_ctx)
    return format_graph_snapshot(pipe.repo, pipe.cfg)

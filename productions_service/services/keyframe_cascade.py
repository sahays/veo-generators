"""Server-side cascade for S8_KEYFRAMES runs (regenerate and resume).

`productions_service._execute_requested_stage` calls `run_keyframes_cascade(pipe, force)`:

* forced ("Regenerate all keyframes"): the pipeline supersedes every active set and
  re-derives all shots; returns `Stage.S8_RENDER` so the service continues with its forced
  S8_RENDER branch (clear runs, mark shots stale, S8_RENDER -> S9_QA -> S10_ASSEMBLE).
* resume ("Resume keyframes", non-forced): re-derives only missing / failed shots (done
  frames reused; re-derived shots are marked stale by the stage), then runs S8_RENDER ->
  S9_QA -> S10_ASSEMBLE non-forced, which render only dirty / unrendered shots. Returns None.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from storygraph.pipeline import Pipeline, Stage

logger = logging.getLogger(__name__)
RESUME_CASCADE: tuple[Stage, ...] = (Stage.S8_RENDER, Stage.S9_QA, Stage.S10_ASSEMBLE)


def run_keyframes_cascade(pipe: Pipeline, force: bool = True) -> Stage | None:
    """Run S8_KEYFRAMES, then cascade downstream (see module docstring)."""
    pipe.run_stage(Stage.S8_KEYFRAMES, force=force)
    _log(pipe, force)
    if force:
        return Stage.S8_RENDER
    for st in RESUME_CASCADE:
        pipe.run_stage(st, force=False)
    return None


def _log(pipe: Pipeline, force: bool) -> None:
    mode = "regenerated" if force else "resumed"
    logger.info(
        f"keyframes {mode}; cascading downstream",
        extra={
            "who": "productions_service",
            "where": "services.keyframe_cascade",
            "what": f"S8_KEYFRAMES {'forced' if force else 'resume'}",
            "when": datetime.now(UTC).isoformat(),
            "why": "keyframes feed render; completed shots continue down the pipeline",
            "how": "S8_KEYFRAMES -> S8_RENDER -> S9_QA -> S10_ASSEMBLE (server-side)",
            "project_id": pipe.repo.project_id,
        },
    )

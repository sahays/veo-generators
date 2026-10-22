"""Server-side cascade for a forced S8_KEYFRAMES run (same rule as every stage regenerate).

`productions_service._execute_requested_stage` calls `run_keyframes_cascade(pipe)` for a
forced S8_KEYFRAMES request: it re-derives every shot's keyframes (the pipeline supersedes the
active sets on force) and returns `Stage.S8_RENDER`, so the service continues with its existing
forced S8_RENDER branch (clear runs, mark shots stale, S8_RENDER -> S9_QA -> S10_ASSEMBLE).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from storygraph.pipeline import Pipeline, Stage

logger = logging.getLogger(__name__)


def run_keyframes_cascade(pipe: Pipeline) -> Stage:
    """Force S8_KEYFRAMES, then hand back S8_RENDER for the downstream server cascade."""
    pipe.run_stage(Stage.S8_KEYFRAMES, force=True)
    logger.info(
        "keyframes regenerated; cascading downstream",
        extra={
            "who": "productions_service",
            "where": "services.keyframe_cascade",
            "what": "S8_KEYFRAMES forced",
            "when": datetime.now(UTC).isoformat(),
            "why": "stage regenerate re-runs every downstream stage",
            "how": "S8_KEYFRAMES -> S8_RENDER -> S9_QA -> S10_ASSEMBLE (server-side)",
            "project_id": pipe.repo.project_id,
        },
    )
    return Stage.S8_RENDER

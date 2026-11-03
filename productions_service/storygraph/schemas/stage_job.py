"""Background stage-run job (`stage_jobs`, id `run_<ts>_<hex>`): live state of one async run.

`StageRun` stays the append-only per-stage history written when a stage finishes. A
`StageJob` is the mutable envelope of one HTTP-triggered run (which may execute several
stages, e.g. the S8_KEYFRAMES -> S8_RENDER -> S9_QA -> S10_ASSEMBLE cascade): its current
stage, `progress`, `heartbeat_at` (liveness) and terminal outcome. `meta/active_job` points
at the project's most recent job (single-flight claim + O(1) status reads).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .base import NodeBase

RunKind = Literal[
    "pipeline",
    "stage",
    "assemble",
    "repair",
    "shot_regenerate",
    "keyframe_regenerate",
    "appearance_regenerate",
]
RunStatus = Literal["queued", "running", "completed", "paused", "failed", "interrupted"]
ProgressUnit = Literal["clips", "frames", "shots"]
LIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})


class RunProgress(BaseModel):
    """`done` of `total` units of the current stage (`current`: shot / item in flight)."""

    done: int = 0
    total: int = 0
    unit: ProgressUnit = "shots"
    current: str | None = None


class StageJob(NodeBase):
    node_type: Literal["StageJob"] = "StageJob"
    kind: RunKind
    label: str
    stage: str | None = None
    stages: list[str] = Field(default_factory=list)
    run_status: RunStatus = "queued"
    progress: RunProgress | None = None
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None

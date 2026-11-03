"""Run liveness (pure): a queued/running run whose heartbeat went stale died with its instance.

The tracker heartbeats every `HEARTBEAT_EVERY_S` while the worker process is alive (also
while a run waits in the executor queue), so `STALE_AFTER_S` (several missed beats) means
the instance is gone: the run is reported `interrupted` and the UI offers Resume.
"""

from __future__ import annotations

from datetime import UTC, datetime

from storygraph.schemas.stage_job import LIVE_STATUSES, RunStatus, StageJob

HEARTBEAT_EVERY_S = 15.0
STALE_AFTER_S = 90.0


def utc_now() -> datetime:
    return datetime.now(UTC)


def effective_status(
    job: StageJob, now: datetime, stale_after_s: float = STALE_AFTER_S
) -> RunStatus:
    """Stored status, except a live run without a recent heartbeat is `interrupted`."""
    if job.run_status not in LIVE_STATUSES:
        return job.run_status
    silent_s = (now - job.heartbeat_at).total_seconds()
    return "interrupted" if silent_s > stale_after_s else job.run_status


def is_live(job: StageJob, now: datetime) -> bool:
    return effective_status(job, now) in LIVE_STATUSES


def interrupted_message(job: StageJob) -> str:
    return (
        f"{job.label} was interrupted (no heartbeat since "
        f"{job.heartbeat_at.isoformat(timespec='seconds')}; the server instance stopped). "
        "Resume to continue from where it left off."
    )

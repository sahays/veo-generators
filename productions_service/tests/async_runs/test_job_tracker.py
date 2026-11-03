"""JobTracker: progress bursts coalesce into one write per tick, totals clamp, and a finished
run is never rewritten by a late tick or late progress (no resurrected "running" runs)."""

from __future__ import annotations

from services.jobs.liveness import utc_now
from services.jobs.tracker import JobTracker
from storygraph.repo.stage_jobs import StageJobRepo
from storygraph.schema import Role
from storygraph.schemas.stage_job import RunProgress, StageJob
from storygraph.store.memory import MemoryStore


def _tracked() -> tuple[JobTracker, StageJobRepo, StageJob]:
    repo = StageJobRepo(MemoryStore("p_tracker"))
    now = utc_now()
    job = repo.put(
        StageJob(
            id="run_t",
            created_by=Role.HUMAN,
            kind="stage",
            label="Run S8_RENDER",
            started_at=now,
            heartbeat_at=now,
        )
    )
    return JobTracker(tick_s=3600, heartbeat_every_s=3600), repo, job


def test_burst_coalesces_and_done_never_exceeds_total() -> None:
    tracker, repo, job = _tracked()
    sink = tracker.track(job, repo)
    sink.stage_started("S8_RENDER")
    sink.add_total(2, "shots")
    for shot in ("shot_1", "shot_2", "shot_3"):
        sink.advance(1, shot)
    assert tracker.flush() == 1 and tracker.flush() == 0
    stored = repo.get(job.id)
    assert stored is not None and stored.stage == "S8_RENDER"
    assert stored.progress == RunProgress(
        done=2, total=2, unit="shots", current="shot_3"
    )


def test_finished_run_is_not_rewritten_by_late_progress() -> None:
    tracker, repo, job = _tracked()
    sink = tracker.track(job, repo)
    sink.advance(1, "shot_1")
    tracker.finish(job.id, lambda j: j.model_copy(update={"run_status": "completed"}))
    sink.advance(1, "late")
    assert tracker.flush() == 0
    stored = repo.get(job.id)
    assert stored is not None and stored.run_status == "completed"
    assert stored.finished_at is not None and stored.progress is not None
    assert stored.progress.current == "shot_1"

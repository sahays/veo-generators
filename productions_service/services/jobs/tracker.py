"""In-process tracker for live runs: progress sink + heartbeat writer.

Stages mutate the in-memory `StageJob` through a `ProgressSink` (cheap, lock-guarded).
One daemon ticker flushes each live run every `tick_s`: it writes the document when the
progress changed (coalescing bursts into <= 1 write per tick) or when the last write is
older than `heartbeat_every_s` (liveness). `finish` writes the terminal state exactly once;
a closed run is never rewritten, so a late tick cannot resurrect a finished run.

Cloud Run note: the productions service is deployed with `--no-cpu-throttling
--min-instances 1 --timeout 3600` (scripts/deploy.sh), so this thread and the executor
threads keep CPU after the 202 response is sent.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from storygraph.repo.stage_jobs import StageJobRepo
from storygraph.schemas.stage_job import ProgressUnit, RunProgress, StageJob

from .liveness import HEARTBEAT_EVERY_S, utc_now

logger = logging.getLogger(__name__)
Mutation = Callable[[StageJob], StageJob]


@dataclass
class _Live:
    job: StageJob
    repo: StageJobRepo
    lock: threading.Lock = field(default_factory=threading.Lock)
    dirty: bool = False
    closed: bool = False
    written_at: float = field(default_factory=time.monotonic)


def _with_total(job: StageJob, n: int, unit: ProgressUnit) -> StageJob:
    cur = job.progress or RunProgress(unit=unit)
    nxt = cur.model_copy(update={"total": cur.total + n, "unit": unit})
    return job.model_copy(update={"progress": nxt})


def _with_done(job: StageJob, n: int, current: str | None) -> StageJob:
    cur = job.progress or RunProgress()
    done = cur.done + n
    done = min(done, cur.total) if cur.total else done
    nxt = cur.model_copy(update={"done": done, "current": current})
    return job.model_copy(update={"progress": nxt})


class RunSink:
    """`storygraph.progress.ProgressSink` for one tracked run."""

    def __init__(self, tracker: JobTracker, run_id: str) -> None:
        self._tracker, self._run_id = tracker, run_id

    def stage_started(self, stage: str) -> None:
        upd: dict[str, Any] = {"stage": stage, "progress": None}
        self._tracker.mutate(self._run_id, lambda j: j.model_copy(update=upd))

    def add_total(self, n: int, unit: ProgressUnit) -> None:
        self._tracker.mutate(self._run_id, lambda j: _with_total(j, n, unit))

    def advance(self, n: int, current: str | None) -> None:
        self._tracker.mutate(self._run_id, lambda j: _with_done(j, n, current))


class JobTracker:
    def __init__(
        self, tick_s: float = 2.0, heartbeat_every_s: float = HEARTBEAT_EVERY_S
    ) -> None:
        self._tick_s, self._beat_s = tick_s, heartbeat_every_s
        self._live: dict[str, _Live] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def track(self, job: StageJob, repo: StageJobRepo) -> RunSink:
        with self._lock:
            self._live[job.id] = _Live(job, repo)
            self._ensure_ticker()
        return RunSink(self, job.id)

    def mutate(self, run_id: str, fn: Mutation) -> None:
        live = self._get(run_id)
        if live is None:
            return
        with live.lock:
            if not live.closed:
                live.job, live.dirty = fn(live.job), True

    def finish(self, run_id: str, fn: Mutation) -> StageJob | None:
        """Apply the terminal mutation, write it once, stop tracking the run."""
        live = self._get(run_id)
        if live is None:
            return None
        with live.lock:
            live.closed = True
            now = utc_now()
            live.job = fn(live.job).model_copy(
                update={"heartbeat_at": now, "finished_at": now}
            )
            live.repo.put(live.job)
        with self._lock:
            self._live.pop(run_id, None)
        return live.job

    def flush(self) -> int:
        """Write every due run (changed, or heartbeat older than the beat); returns writes."""
        with self._lock:
            lives = list(self._live.values())
        return sum(self._flush_one(live) for live in lives)

    def _flush_one(self, live: _Live) -> int:
        with live.lock:
            stale = time.monotonic() - live.written_at >= self._beat_s
            if live.closed or not (live.dirty or stale):
                return 0
            job = live.job.model_copy(update={"heartbeat_at": utc_now()})
            try:
                live.repo.put(job)
            except Exception as exc:  # noqa: BLE001 - keep beating; retry next tick
                _log_write_failure(job, exc)
                return 0
            live.job, live.dirty, live.written_at = job, False, time.monotonic()
            return 1

    def _get(self, run_id: str) -> _Live | None:
        with self._lock:
            return self._live.get(run_id)

    def _ensure_ticker(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._loop, name="stage-job-heartbeat", daemon=True
            )
            self._thread.start()

    def _loop(self) -> None:
        while True:
            time.sleep(self._tick_s)
            self.flush()


def _log_write_failure(job: StageJob, exc: Exception) -> None:
    logger.warning(
        "stage job heartbeat write failed",
        extra={
            "who": "productions_service",
            "where": "services.jobs.tracker",
            "what": "heartbeat_write_failed",
            "when": utc_now().isoformat(),
            "why": f"{type(exc).__name__}: {exc}"[:300],
            "how": "StageJobRepo.put (retried next tick)",
            "run_id": job.id,
        },
    )

"""StageJob repository (`stage_jobs` + pointer `meta/active_job`): async run state.

Reads are O(1) document gets: the pointer names the project's most recent run, so the
status endpoint never queries. `claim` is the single-flight guard: inside one store
transaction it reads the pointer's run and either refuses (a live run exists) or writes
the new run + pointer, marking a dead (stale-heartbeat) predecessor `interrupted`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from ..schemas.stage_job import LIVE_STATUSES, StageJob
from ..store.base import GraphStore
from ..store.codec import decode, encode

COLLECTION: Final[str] = "stage_jobs"
POINTER: Final[tuple[str, str]] = ("meta", "active_job")


class RunConflict(Exception):
    """A live run already owns the project (single-flight)."""

    def __init__(self, active: StageJob) -> None:
        super().__init__(f"run {active.id} is {active.run_status}")
        self.active = active


class StageJobRepo:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def get(self, run_id: str) -> StageJob | None:
        raw = self.store.get(COLLECTION, run_id)
        return decode(raw, StageJob) if raw else None

    def put(self, job: StageJob) -> StageJob:
        self.store.set(COLLECTION, job.id, encode(job))
        return job

    def latest(self) -> StageJob | None:
        """The project's most recent run (live or finished), via the pointer."""
        ptr = self.store.get(*POINTER)
        return self.get(str(ptr["run_id"])) if ptr and ptr.get("run_id") else None

    def claim(self, job: StageJob, is_live: Callable[[StageJob], bool]) -> None:
        """Atomically make `job` the active run; raises `RunConflict` if one is live."""
        with self.store.transaction() as tx:
            ptr = tx.get(*POINTER)
            raw = tx.get(COLLECTION, str(ptr["run_id"])) if ptr else None
            prev = decode(raw, StageJob) if raw else None
            if prev is not None and is_live(prev):
                raise RunConflict(prev)
            if prev is not None and prev.run_status in LIVE_STATUSES:
                dead = prev.model_copy(update={"run_status": "interrupted"})
                tx.set(COLLECTION, prev.id, encode(dead))
            tx.set(COLLECTION, job.id, encode(job))
            tx.set(*POINTER, {"run_id": job.id})

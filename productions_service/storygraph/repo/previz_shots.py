"""Previz shot records (`previz_shots`) and background run status (`previz_runs`).

`PrevizShot` is versioned per shot like `KeyframeSet`: a new render creates `pzs_<shot>_<n>`
as the single `active` version (older ones `superseded`); status transitions of the active
version during one run (running -> done/failed, variant outputs, promote) update it in place.
Lookups are single indexed queries on (`shot_id`, `set_status`) or (`set_status`).
"""

from __future__ import annotations

from typing import Final

from ..schemas.previz import PrevizRun, PrevizShot
from ..store.base import GraphStore
from ..store.codec import decode, encode

SHOTS: Final[str] = "previz_shots"
RUNS: Final[str] = "previz_runs"


class PrevizShotRepo:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def _active(self, shot_id: str | None = None) -> list[PrevizShot]:
        filters = [("set_status", "==", "active")]
        if shot_id is not None:
            filters.insert(0, ("shot_id", "==", shot_id))
        return [decode(r, PrevizShot) for r in self.store.query(SHOTS, filters=filters)]

    def active_for_shot(self, shot_id: str) -> PrevizShot | None:
        rows = self._active(shot_id)
        return max(rows, key=lambda p: p.version) if rows else None

    def active_by_shot(self) -> dict[str, PrevizShot]:
        out: dict[str, PrevizShot] = {}
        for row in sorted(self._active(), key=lambda p: p.version):
            out[row.shot_id] = row
        return out

    def put(self, ps: PrevizShot) -> PrevizShot:
        """In-place update of one version (status / variants / promote)."""
        self.store.set(SHOTS, ps.id, encode(ps))
        return ps

    def create(self, draft: PrevizShot) -> PrevizShot:
        """Store `draft` as the shot's next version and make it the single active one."""
        current = self._active(draft.shot_id)
        number = max((p.version for p in current), default=0) + 1
        for old in current:
            self.put(old.model_copy(update={"set_status": "superseded"}))
        parent = max(current, key=lambda p: p.version).id if current else None
        return self.put(
            draft.model_copy(
                update={
                    "id": f"pzs_{draft.shot_id}_{number}",
                    "version": number,
                    "set_status": "active",
                    "parent_id": parent,
                }
            )
        )


class PrevizRunRepo:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def put(self, run: PrevizRun) -> PrevizRun:
        self.store.set(RUNS, run.id, encode(run))
        return run

    def get(self, run_id: str) -> PrevizRun | None:
        raw = self.store.get(RUNS, run_id)
        return decode(raw, PrevizRun) if raw else None

    def latest(self) -> PrevizRun | None:
        rows = self.store.query(RUNS, order_by="-created_at", limit=1)
        return decode(rows[0], PrevizRun) if rows else None

    def running(self) -> list[PrevizRun]:
        rows = self.store.query(RUNS, filters=[("run_status", "==", "running")])
        return [decode(r, PrevizRun) for r in rows]

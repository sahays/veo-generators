"""KeyframeSet repository (`keyframe_sets`): immutable per-shot keyframe versions.

Lookups are single indexed queries: active set per shot (`shot_id`, `set_status`), all
active sets of the project (`set_status`), and a shot's lineage ordered by `version`.
Activation rewrites only the currently-active rows of that shot (normally one).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Final

from ..schemas.keyframes import KeyframeFrame, KeyframeSet
from ..store.base import Filter, GraphStore
from ..store.codec import decode, encode

logger = logging.getLogger(__name__)
COLLECTION: Final[str] = "keyframe_sets"


def _log(what: str, why: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.repo",
            "where": "repo.keyframe_sets",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "supersede active rows, write new version",
            **extra,
        },
    )


class KeyframeSetRepo:
    """Typed access to the project's `keyframe_sets` collection."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def _query(
        self,
        filters: list[Filter],
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[KeyframeSet]:
        rows = self.store.query(
            COLLECTION, filters=filters, order_by=order_by, limit=limit
        )
        return [decode(r, KeyframeSet) for r in rows]

    def _put(self, ks: KeyframeSet) -> KeyframeSet:
        self.store.set(COLLECTION, ks.id, encode(ks))
        return ks

    def get(self, set_id: str) -> KeyframeSet | None:
        raw = self.store.get(COLLECTION, set_id)
        return decode(raw, KeyframeSet) if raw else None

    def list_for_shot(self, shot_id: str) -> list[KeyframeSet]:
        return self._query([("shot_id", "==", shot_id)], order_by="version")

    def active_for_shot(self, shot_id: str) -> KeyframeSet | None:
        rows = self._query([("shot_id", "==", shot_id), ("set_status", "==", "active")])
        return max(rows, key=lambda s: s.version) if rows else None

    def active_by_shot(self) -> dict[str, KeyframeSet]:
        return {s.shot_id: s for s in self._query([("set_status", "==", "active")])}

    def _next_number(self, shot_id: str) -> int:
        latest = self._query([("shot_id", "==", shot_id)], order_by="-version", limit=1)
        return latest[0].version + 1 if latest else 1

    def create(self, draft: KeyframeSet) -> KeyframeSet:
        """Store `draft` as the shot's next version and make it the single active set."""
        number = self._next_number(draft.shot_id)
        ks = draft.model_copy(
            update={
                "id": f"kfs_{draft.shot_id}_{number}",
                "version": number,
                "set_status": "active",
            }
        )
        self.supersede_shot(draft.shot_id)
        stored = self._put(ks)
        _log(
            "keyframe_set_created",
            draft.reason or "new keyframes",
            shot_id=draft.shot_id,
            keyframe_set_id=stored.id,
            plan_hash=draft.plan_hash,
            needs_manual_edit=draft.needs_manual_edit,
        )
        return stored

    def supersede_shot(self, shot_id: str) -> int:
        """Supersede the shot's active set(s); returns how many rows changed."""
        active = self._query(
            [("shot_id", "==", shot_id), ("set_status", "==", "active")]
        )
        for ks in active:
            self._put(ks.model_copy(update={"set_status": "superseded"}))
        return len(active)

    def supersede_all(self) -> int:
        """Supersede every active set (stage regenerate)."""
        active = self._query([("set_status", "==", "active")])
        for ks in active:
            self._put(ks.model_copy(update={"set_status": "superseded"}))
        _log("keyframe_sets_superseded", "stage regenerate", count=len(active))
        return len(active)

    def replace_frames(
        self, base: KeyframeSet, frames: list[KeyframeFrame], reason: str
    ) -> KeyframeSet:
        """New active version of `base` with `frames` (human edit / partial re-derive)."""
        draft = base.model_copy(
            update={
                "frames": frames,
                "reason": reason,
                "parent_id": base.id,
                "needs_manual_edit": any(f.status == "manual_edit" for f in frames),
            }
        )
        return self.create(draft)

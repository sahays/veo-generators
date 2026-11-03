"""Previz location layouts (`previz_layouts`): one active version per location.

Modelled on `KeyframeSetRepo`: `create` stores the draft as `pzl_<loc>_<n>`, the single
`active` version, superseding the previous one. Lookups are single indexed queries on
(`location_id`, `set_status`) or (`location_id`) ordered by `version`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Final

from ..schemas.previz import PrevizLayout
from ..store.base import Filter, GraphStore
from ..store.codec import decode, encode

logger = logging.getLogger(__name__)
COLLECTION: Final[str] = "previz_layouts"


def _log(what: str, why: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.repo",
            "where": "repo.previz_layouts",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "supersede active rows, write new version",
            **extra,
        },
    )


class PrevizLayoutRepo:
    """Typed access to the project's `previz_layouts` collection."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def _query(
        self,
        filters: list[Filter],
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[PrevizLayout]:
        rows = self.store.query(
            COLLECTION, filters=filters, order_by=order_by, limit=limit
        )
        return [decode(r, PrevizLayout) for r in rows]

    def _put(self, layout: PrevizLayout) -> PrevizLayout:
        self.store.set(COLLECTION, layout.id, encode(layout))
        return layout

    def get(self, layout_id: str) -> PrevizLayout | None:
        raw = self.store.get(COLLECTION, layout_id)
        return decode(raw, PrevizLayout) if raw else None

    def list(self, location_id: str | None = None) -> list[PrevizLayout]:
        """Every version (of one location when given), oldest first."""
        filters: list[Filter] = (
            [("location_id", "==", location_id)] if location_id else []
        )
        return self._query(filters, order_by="version")

    def list_active(self) -> list[PrevizLayout]:
        """The active version of every location (one indexed query)."""
        rows = self._query([("set_status", "==", "active")])
        return sorted(rows, key=lambda p: p.location_id)

    def active_for_location(self, location_id: str) -> PrevizLayout | None:
        rows = self._active(location_id)
        return max(rows, key=lambda p: p.version) if rows else None

    def _active(self, location_id: str) -> list[PrevizLayout]:
        return self._query(
            [("location_id", "==", location_id), ("set_status", "==", "active")]
        )

    def _next_number(self, location_id: str) -> int:
        latest = self._query(
            [("location_id", "==", location_id)], order_by="-version", limit=1
        )
        return latest[0].version + 1 if latest else 1

    def create(self, draft: PrevizLayout, why: str = "inputs changed") -> PrevizLayout:
        """Store `draft` as the location's next version and make it the single active one."""
        number = self._next_number(draft.location_id)
        for old in self._active(draft.location_id):
            self._put(old.model_copy(update={"set_status": "superseded"}))
        stored = self._put(
            draft.model_copy(
                update={
                    "id": f"pzl_{draft.location_id}_{number}",
                    "version": number,
                    "set_status": "active",
                }
            )
        )
        _log(
            "previz_layout_created",
            why,
            location_id=draft.location_id,
            previz_layout_id=stored.id,
            source_hash=draft.layout.source_hash,
        )
        return stored

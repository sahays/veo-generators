"""Cursor pagination over the append-only audit log (newest first), O(limit) reads per page.

Cursor = `<created_at ISO>|<id>,<id>...`: the boundary timestamp plus the ids already served
at exactly that timestamp, so equal-timestamp entries are neither skipped nor repeated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

AUDIT_PAGE_DEFAULT = 30
AUDIT_PAGE_MAX = 200
CURSOR_MAX_LEN = 2048
_TS_RE = re.compile(r"^[0-9T:.+\-Z]{10,40}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


@dataclass(frozen=True)
class AuditCursor:
    created_at: str
    tie_ids: frozenset[str]

    def encode(self) -> str:
        return f"{self.created_at}|{','.join(sorted(self.tie_ids))}"


def decode_cursor(raw: str | None) -> AuditCursor | None:
    """Parse and strictly validate a client cursor (rejects anything not produced by us)."""
    if not raw:
        return None
    ts, sep, ids_part = raw.partition("|")
    ids = frozenset(i for i in ids_part.split(",") if i)
    if (
        len(raw) > CURSOR_MAX_LEN
        or not sep
        or not _TS_RE.match(ts)
        or not all(_ID_RE.match(i) for i in ids)
    ):
        raise HTTPException(status_code=400, detail="Invalid audit-log cursor")
    return AuditCursor(created_at=ts, tie_ids=ids)


def query_window(cursor: AuditCursor | None, limit: int) -> tuple[list[Any], int]:
    """(store filters, row limit) for one page: +ties to skip, +1 to detect a further page."""
    if cursor is None:
        return [], limit + 1
    return [("created_at", "<=", cursor.created_at)], limit + len(cursor.tie_ids) + 1


def paginate(
    rows: list[dict[str, Any]], cursor: AuditCursor | None, limit: int
) -> tuple[list[dict[str, Any]], AuditCursor | None]:
    """Drop already-served boundary rows, cut to `limit`, and compute the next cursor."""
    if cursor is not None:
        rows = [
            r
            for r in rows
            if not (
                r.get("created_at") == cursor.created_at
                and r.get("id") in cursor.tie_ids
            )
        ]
    page, has_more = rows[:limit], len(rows) > limit
    if not page or not has_more:
        return page, None
    last_ts = str(page[-1].get("created_at"))
    ties = {str(r.get("id")) for r in page if r.get("created_at") == last_ts}
    if cursor is not None and cursor.created_at == last_ts:
        ties |= cursor.tie_ids
    return page, AuditCursor(created_at=last_ts, tie_ids=frozenset(ties))

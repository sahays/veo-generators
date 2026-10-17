"""Append-only audit log writer for StoryGraph mutations."""

from __future__ import annotations

import uuid

from .schema import AuditEntry, Role
from .store.base import GraphStore
from .store.codec import encode


def append_audit(
    store: GraphStore,
    role: Role,
    tool: str,
    target_id: str,
    before_version: int | None,
    after_version: int,
    summary: str = "",
) -> AuditEntry:
    entry = AuditEntry(
        id=f"aud_{uuid.uuid4().hex[:12]}",
        created_by=role,
        role=role,
        tool=tool,
        target_id=target_id,
        before_version=before_version,
        after_version=after_version,
        summary=summary,
    )
    store.set("audit_log", entry.id, encode(entry))
    return entry

"""Single source of truth for resetting a shot's automatic-repair bookkeeping.

Any change to a shot's render content (or an explicit user re-render) starts a fresh
repair budget: attempts back to zero and the manual-edit flag cleared.
"""

from __future__ import annotations

from typing import Any

from ..schema import Shot


def repair_reset_update() -> dict[str, Any]:
    """`model_copy(update=...)` payload that clears all repair bookkeeping."""
    return {"repair_attempts": 0, "needs_manual_edit": False, "manual_edit_reasons": []}


def mark_stale_and_reset(shot: Shot, reason: str) -> Shot:
    """Return `shot` marked stale with `reason` and a fresh repair budget."""
    return shot.model_copy(
        update={"stale": True, "stale_reason": reason, **repair_reset_update()}
    )


__all__ = ["mark_stale_and_reset", "repair_reset_update"]

"""DEPRECATED pass-through: model retries live in the process GenAI governor.

Quota / capacity / 5xx retries, pacing and back-off are applied once, inside every model
adapter (`storygraph.adapters.governor.governed`). Wrapping an adapter call here again would
stack a second policy on top, so `with_retry` now just calls `fn`. It is kept only so
existing callers (the previz workstream) keep importing; new code calls adapters directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_retry(fn: Callable[[], T], what: str = "") -> T:
    """Call `fn` once; `what` is ignored (the governor logs caller scope and attempts)."""
    del what
    return fn()

"""Who is calling the model: a context-local (stage, item) scope for governor logs.

Stages set it per unit of work (`with call_scope("S8_KEYFRAMES", shot.id): ...`) inside the
worker thread that does the work, so every governed call logged underneath names its caller.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_SCOPE: ContextVar[tuple[str, str]] = ContextVar("genai_call_scope", default=("", ""))


@contextmanager
def call_scope(stage: str, item: str = "") -> Iterator[None]:
    token = _SCOPE.set((stage, item))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def current_scope() -> str:
    stage, item = _SCOPE.get()
    return "/".join(p for p in (stage, item) if p) or "unscoped"

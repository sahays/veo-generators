"""Process-wide progress reporting for long-running stages (async stage runs).

Stages report through module functions keyed by project id, so no stage signature has to
carry a reporter and worker threads (scene pools) need no context propagation. A sink is
bound only while a background run of that project executes (`services.jobs.executor`);
everywhere else (tests, sync callers, scripts) every call is a cheap no-op.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from .schemas.stage_job import ProgressUnit


class ProgressSink(Protocol):
    def stage_started(self, stage: str) -> None: ...

    def add_total(self, n: int, unit: ProgressUnit) -> None: ...

    def advance(self, n: int, current: str | None) -> None: ...


_sinks: dict[str, ProgressSink] = {}
_lock = threading.Lock()


@contextmanager
def bound(project_id: str, sink: ProgressSink) -> Iterator[None]:
    """Route `project_id`'s progress to `sink` for the duration of the block."""
    with _lock:
        _sinks[project_id] = sink
    try:
        yield
    finally:
        with _lock:
            if _sinks.get(project_id) is sink:
                del _sinks[project_id]


def _sink(project_id: str) -> ProgressSink | None:
    with _lock:
        return _sinks.get(project_id)


def stage_started(project_id: str, stage: str) -> None:
    """A new stage began: the sink resets progress to indeterminate."""
    sink = _sink(project_id)
    if sink is not None:
        sink.stage_started(stage)


def add_total(project_id: str, n: int, unit: ProgressUnit) -> None:
    """Grow the current stage's total (scenes plan in parallel, so totals accumulate)."""
    sink = _sink(project_id)
    if sink is not None and n > 0:
        sink.add_total(n, unit)


def advance(project_id: str, n: int = 1, current: str | None = None) -> None:
    """`n` more units of the current stage are done (`current`: item just finished)."""
    sink = _sink(project_id)
    if sink is not None and n > 0:
        sink.advance(n, current)

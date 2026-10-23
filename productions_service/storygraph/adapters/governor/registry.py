"""The process-wide default `Governor` (lazy, from `Config.load().genai`) and `governed()`.

Model quotas are per GCP project, so ONE governor per process must see every call — adapter
instances (and repair paths that build their own adapters) all route through this registry.
Tests swap it with `use_governor(...)`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from ...config import Config
from .governor import Governor

T = TypeVar("T")


class _Holder:
    lock = threading.Lock()
    current: Governor | None = None


def default_governor() -> Governor:
    current = _Holder.current
    if current is not None:
        return current
    with _Holder.lock:
        if _Holder.current is None:
            _Holder.current = Governor(Config.load().genai)
        return _Holder.current


@contextmanager
def use_governor(governor: Governor) -> Iterator[Governor]:
    """Temporarily replace the process governor (tests, offline experiments)."""
    with _Holder.lock:
        previous, _Holder.current = _Holder.current, governor
    try:
        yield governor
    finally:
        with _Holder.lock:
            _Holder.current = previous


def governed(model: str, fn: Callable[[], T]) -> T:
    """THE seam: run one raw provider request for `model` under the process governor."""
    return default_governor().call(model, fn)

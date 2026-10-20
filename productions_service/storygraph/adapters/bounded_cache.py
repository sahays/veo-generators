"""Small bounded LRU cache keyed by content digest (shared by embedding/transcription adapters)."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from typing import Generic, TypeVar

V = TypeVar("V")


def digest(data: bytes, salt: str = "") -> str:
    """Stable content key (sha256 of salt + bytes)."""
    return hashlib.sha256(salt.encode() + data).hexdigest()


class BoundedCache(Generic[V]):
    """O(1) get/put LRU with a fixed capacity (oldest entry evicted first)."""

    def __init__(self, capacity: int = 256) -> None:
        self._capacity = max(1, capacity)
        self._items: OrderedDict[str, V] = OrderedDict()

    def get(self, key: str) -> V | None:
        if key not in self._items:
            return None
        self._items.move_to_end(key)
        return self._items[key]

    def put(self, key: str, value: V) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        if len(self._items) > self._capacity:
            self._items.popitem(last=False)

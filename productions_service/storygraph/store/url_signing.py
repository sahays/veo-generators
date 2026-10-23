"""Signed-URL cache and bounded-parallel batch signing for BlobStores.

On Cloud Run the runtime credentials cannot sign locally, so every V4 signature is an IAM
`signBlob` HTTPS round trip (~70-150 ms). A signed URL is valid for its full expiration, so
caching it for a shorter TTL is safe and turns repeated snapshot polls into O(1) lookups.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor

SIGN_EXPIRATION_MINUTES: int = 60
# Served URLs always keep >= 15 minutes of validity.
SIGN_CACHE_TTL_S: float = 45 * 60
SIGN_CACHE_MAX_ENTRIES: int = 5000
SIGN_MAX_WORKERS: int = 16


class SignedUrlCache:
    """Thread-safe TTL + LRU cache mapping a canonical blob URI to its signed URL."""

    def __init__(
        self,
        ttl_s: float = SIGN_CACHE_TTL_S,
        max_entries: int = SIGN_CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, uri: str) -> str | None:
        with self._lock:
            hit = self._entries.get(uri)
            if hit is None:
                return None
            if hit[0] <= self._clock():
                del self._entries[uri]
                return None
            self._entries.move_to_end(uri)
            return hit[1]

    def put(self, uri: str, signed: str) -> None:
        with self._lock:
            self._entries[uri] = (self._clock() + self._ttl_s, signed)
            self._entries.move_to_end(uri)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


def sign_many(
    sign_one: Callable[[str], str],
    uris: Iterable[str],
    max_workers: int = SIGN_MAX_WORKERS,
) -> dict[str, str]:
    """Sign each distinct non-empty URI once, using a bounded thread pool for network signers."""
    unique = sorted({u for u in uris if u})
    if len(unique) <= 1:
        return {u: sign_one(u) for u in unique}
    with ThreadPoolExecutor(max_workers=min(max_workers, len(unique))) as pool:
        return dict(zip(unique, pool.map(sign_one, unique)))


def sign_all(blobs: object, uris: Iterable[str]) -> dict[str, str]:
    """Batch-sign via `blobs.sign_urls` when available, else per-URI `sign_url` (identity fallback)."""
    batch = getattr(blobs, "sign_urls", None)
    if callable(batch):
        return dict(batch(uris))
    single = getattr(blobs, "sign_url", None)
    sign_one: Callable[[str], str] = single if callable(single) else (lambda u: u)
    return {u: sign_one(u) for u in {u for u in uris if u}}

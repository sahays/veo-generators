"""Blob store that reads production blobs (gs:// or file://) but writes only locally.

Reads are cached on disk by URI hash, so reruns do not re-download reference sheets.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from ...store import GcsBlobStore, LocalBlobStore


class ReadThroughLocalBlobs:
    """`BlobStore`: get_bytes from GCS (cached), put_bytes to a local directory only."""

    def __init__(
        self, reader: GcsBlobStore, writer: LocalBlobStore, cache_dir: Path
    ) -> None:
        self.reader, self.writer, self.cache_dir = reader, writer, cache_dir
        self.project_id = writer.project_id
        cache_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, rel_path: str, data: bytes, content_type: str) -> str:
        return self.writer.put_bytes(rel_path, data, content_type)

    def get_bytes(self, uri: str) -> bytes:
        if uri.startswith("file://"):
            return self.writer.get_bytes(uri)
        cached = self.cache_dir / hashlib.sha256(uri.encode("utf-8")).hexdigest()[:24]
        if not cached.is_file():
            cached.write_bytes(self.reader.get_bytes(uri))
        return cached.read_bytes()

    def exists(self, uri: str) -> bool:
        return (
            self.writer.exists(uri)
            if uri.startswith("file://")
            else self.reader.exists(uri)
        )

    def sign_url(self, uri: str) -> str:
        return uri

    def sign_urls(self, uris: Iterable[str]) -> dict[str, str]:
        return {u: u for u in uris if u}

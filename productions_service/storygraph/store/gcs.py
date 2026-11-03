"""Local filesystem and Google Cloud Storage implementations of BlobStore."""

from __future__ import annotations

import datetime
import shutil
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import google.auth
import google.auth.credentials
from google.auth.transport import requests as auth_requests
from google.cloud import storage

from ..errors import NotFound
from .url_signing import SIGN_EXPIRATION_MINUTES, SignedUrlCache, sign_many

# Process-wide: URIs embed the bucket, so one cache safely serves every project/instance.
_SIGNED_URLS = SignedUrlCache()


@lru_cache(maxsize=1)
def _shared_client() -> storage.Client:
    """One storage client per process (a store is built per request; auth + HTTP pool reused)."""
    return storage.Client()


@lru_cache(maxsize=1)
def _shared_credentials() -> google.auth.credentials.Credentials:
    """Process-wide ADC: the access token used for IAM URL signing is refreshed once per expiry."""
    creds, _ = google.auth.default()
    return creds


class LocalBlobStore:
    """Filesystem-backed BlobStore for unit tests and local development."""

    def __init__(self, root_dir: str | Path, project_id: str = "default") -> None:
        self.root_dir = Path(root_dir).resolve()
        self.project_id = project_id
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_uri(self, uri: str) -> Path:
        if uri.startswith("file://"):
            parsed = urlparse(uri)
            return Path(parsed.path)
        return Path(uri)

    def put_bytes(self, rel_path: str, data: bytes, content_type: str) -> str:
        clean_rel = rel_path.lstrip("/")
        target = self.root_dir / self.project_id / clean_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"file://{target}"

    def get_bytes(self, uri: str) -> bytes:
        path = self._resolve_uri(uri)
        if not path.is_file():
            raise NotFound(f"Blob not found at {uri}")
        return path.read_bytes()

    def exists(self, uri: str) -> bool:
        path = self._resolve_uri(uri)
        return path.is_file()

    def sign_url(self, uri: str) -> str:
        return uri

    def sign_urls(self, uris: Iterable[str]) -> dict[str, str]:
        return {u: u for u in uris if u}

    def delete_project_blobs(self, extra_uris: Iterable[str] = ()) -> int:
        """Delete local project directory and any extra `file://` URIs; return deleted count."""
        deleted = 0
        proj_dir = self.root_dir / self.project_id
        if proj_dir.is_dir():
            deleted += sum(1 for p in proj_dir.rglob("*") if p.is_file())
            shutil.rmtree(proj_dir, ignore_errors=True)
        for uri in {u for u in extra_uris if u}:
            path = self._resolve_uri(uri)
            if path.is_file():
                try:
                    path.unlink()
                    deleted += 1
                except OSError:
                    pass
        return deleted


class GcsBlobStore:
    """Google Cloud Storage BlobStore with cached credential URL signing."""

    def __init__(
        self,
        bucket_name: str,
        project_id: str,
        prefix: str = "projects",
        client: storage.Client | None = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.project_id = project_id
        self.prefix = prefix.strip("/")
        self._client = client or _shared_client()
        self._bucket = self._client.bucket(bucket_name)
        self._credentials = _shared_credentials()

    def _blob_path(self, rel_path: str) -> str:
        clean_rel = rel_path.lstrip("/")
        return f"{self.prefix}/{self.project_id}/{clean_rel}"

    def _parse_gs(self, uri: str) -> tuple[str, str]:
        if not uri.startswith("gs://"):
            raise ValueError(f"Expected gs:// URI, got {uri!r}")
        without = uri[5:]
        bucket_name, _, blob_name = without.partition("/")
        return bucket_name, blob_name

    def put_bytes(self, rel_path: str, data: bytes, content_type: str) -> str:
        blob_name = self._blob_path(rel_path)
        blob = self._bucket.blob(blob_name)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{blob_name}"

    def get_bytes(self, uri: str) -> bytes:
        if uri.startswith("file://"):
            path = Path(urlparse(uri).path)
            if not path.is_file():
                raise NotFound(f"Local blob not found: {uri}")
            return path.read_bytes()
        bucket_name, blob_name = self._parse_gs(uri)
        bucket = (
            self._bucket
            if bucket_name == self.bucket_name
            else self._client.bucket(bucket_name)
        )
        blob = bucket.blob(blob_name)
        if not blob.exists():
            raise NotFound(f"GCS blob not found: {uri}")
        return blob.download_as_bytes()

    def exists(self, uri: str) -> bool:
        if uri.startswith("file://"):
            return Path(urlparse(uri).path).is_file()
        bucket_name, blob_name = self._parse_gs(uri)
        bucket = (
            self._bucket
            if bucket_name == self.bucket_name
            else self._client.bucket(bucket_name)
        )
        return bucket.blob(blob_name).exists()

    def sign_url(
        self, uri: str, expiration_minutes: int = SIGN_EXPIRATION_MINUTES
    ) -> str:
        if not uri or not uri.startswith("gs://"):
            return uri
        cached = _SIGNED_URLS.get(uri)
        if cached is not None:
            return cached
        signed = self._sign_uncached(uri, expiration_minutes)
        if signed != uri:  # never cache a failed (unsigned) fallback
            _SIGNED_URLS.put(uri, signed)
        return signed

    def sign_urls(self, uris: Iterable[str]) -> dict[str, str]:
        """Sign many URIs: cache hits are O(1); misses run on a bounded thread pool."""
        return sign_many(self.sign_url, uris)

    def _collect_prefix_uris(self) -> set[str]:
        """List all `gs://` blob URIs under the project's GCS prefixes."""
        found: set[str] = set()
        prefixes = (
            f"{self.prefix}/{self.project_id}/",
            f"productions/{self.project_id}/",
            f"generated/{self.project_id}/",
        )
        for pfx in dict.fromkeys(prefixes):
            try:
                for blob in self._client.list_blobs(self.bucket_name, prefix=pfx):
                    found.add(f"gs://{self.bucket_name}/{blob.name}")
            except Exception:
                pass
        return found

    def delete_project_blobs(self, extra_uris: Iterable[str] = ()) -> int:
        """Delete all GCS blobs under the project prefixes plus any referenced `gs://` URIs."""
        targets = self._collect_prefix_uris() | {
            u for u in extra_uris if u and u.startswith("gs://")
        }
        _SIGNED_URLS.evict(targets)
        deleted = 0
        for uri in sorted(targets):
            try:
                bucket_name, blob_name = self._parse_gs(uri)
                if not blob_name:
                    continue
                bucket = (
                    self._bucket
                    if bucket_name == self.bucket_name
                    else self._client.bucket(bucket_name)
                )
                bucket.blob(blob_name).delete()
                deleted += 1
            except Exception:
                pass
        return deleted

    def _sign_uncached(self, uri: str, expiration_minutes: int) -> str:
        try:
            bucket_name, blob_name = self._parse_gs(uri)
            bucket = (
                self._bucket
                if bucket_name == self.bucket_name
                else self._client.bucket(bucket_name)
            )
            blob = bucket.blob(blob_name)
            expiration = datetime.timedelta(minutes=expiration_minutes)
            if hasattr(self._credentials, "sign_bytes"):
                return blob.generate_signed_url(
                    version="v4", expiration=expiration, method="GET"
                )
            if not self._credentials.valid:
                self._credentials.refresh(auth_requests.Request())
            sa_email = getattr(self._credentials, "service_account_email", None)
            if sa_email and getattr(self._credentials, "token", None):
                return blob.generate_signed_url(
                    version="v4",
                    expiration=expiration,
                    method="GET",
                    service_account_email=sa_email,
                    access_token=self._credentials.token,
                )
        except Exception:
            pass
        return uri

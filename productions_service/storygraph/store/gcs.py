"""Local filesystem and Google Cloud Storage implementations of BlobStore."""

from __future__ import annotations

import datetime
from pathlib import Path
from urllib.parse import urlparse

import google.auth
from google.auth.transport import requests as auth_requests
from google.cloud import storage

from ..errors import NotFound


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
        self._client = client or storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._credentials, _ = google.auth.default()

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

    def sign_url(self, uri: str, expiration_minutes: int = 60) -> str:
        if not uri or not uri.startswith("gs://"):
            return uri
        try:
            bucket_name, blob_name = self._parse_gs(uri)
            bucket = (
                self._bucket
                if bucket_name == self.bucket_name
                else self._client.bucket(bucket_name)
            )
            blob = bucket.blob(blob_name)
            if hasattr(self._credentials, "sign_bytes"):
                return blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=expiration_minutes),
                    method="GET",
                )
            if not self._credentials.valid:
                self._credentials.refresh(auth_requests.Request())
            sa_email = getattr(self._credentials, "service_account_email", None)
            if sa_email and getattr(self._credentials, "token", None):
                return blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=expiration_minutes),
                    method="GET",
                    service_account_email=sa_email,
                    access_token=self._credentials.token,
                )
        except Exception:
            pass
        return uri

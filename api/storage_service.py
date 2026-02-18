import os
import google.auth
from datetime import datetime, timedelta, timezone
from google.cloud import storage

SIGN_DURATION = timedelta(hours=48)
REFRESH_THRESHOLD = timedelta(minutes=5)


class StorageService:
    def __init__(self):
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.bucket_name = os.getenv("GCS_BUCKET", f"{self.project_id}-veogen-assets")
        self.client = storage.Client(project=self.project_id)
        self.credentials, self.project = google.auth.default()

        # Ensure bucket exists
        try:
            self.bucket = self.client.get_bucket(self.bucket_name)
        except Exception as e:
            if "404" in str(e):
                try:
                    self.bucket = self.client.create_bucket(self.bucket_name)
                except Exception as create_error:
                    print(
                        f"Failed to create bucket '{self.bucket_name}': {create_error}"
                    )
                    raise
            else:
                print(f"Failed to access bucket '{self.bucket_name}': {e}")
                raise

    def upload_file(
        self, content: bytes, destination_path: str, content_type: str
    ) -> str:
        blob = self.bucket.blob(destination_path)
        blob.upload_from_string(content, content_type=content_type)
        return f"gs://{self.bucket_name}/{destination_path}"

    def upload_bytes(
        self, data: bytes, destination_path: str, content_type: str = "image/png"
    ) -> str:
        blob = self.bucket.blob(destination_path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{destination_path}"

    def _generate_signed_url(self, gcs_uri: str) -> dict:
        """Generate a signed URL and return it with expiration metadata."""
        path = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
        blob = self.bucket.blob(path)

        from google.auth.transport import requests

        request = requests.Request()
        self.credentials.refresh(request)

        expires_at = datetime.now(timezone.utc) + SIGN_DURATION
        url = blob.generate_signed_url(
            version="v4",
            expiration=SIGN_DURATION,
            method="GET",
            service_account_email=self.credentials.service_account_email,
            access_token=self.credentials.token,
        )
        return {"url": url, "expires_at": expires_at.isoformat()}

    def get_signed_url(self, gcs_uri: str) -> str:
        if not gcs_uri.startswith("gs://"):
            return gcs_uri
        return self._generate_signed_url(gcs_uri)["url"]

    def get_file_size(self, gcs_uri: str) -> int:
        """Return the size in bytes of a GCS object, or 0 if not found."""
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return 0
        try:
            path = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
            blob = self.bucket.blob(path)
            blob.reload()
            return blob.size or 0
        except Exception:
            return 0

    def recover_gcs_uri(self, url: str) -> str | None:
        """Try to extract a gs:// URI from an expired signed URL."""
        if not url or url.startswith("gs://"):
            return url
        if self.bucket_name in url:
            try:
                path = url.split(f"/{self.bucket_name}/")[1].split("?")[0]
                return f"gs://{self.bucket_name}/{path}"
            except (IndexError, ValueError):
                pass
        return None

    def generate_upload_signed_url(
        self, destination_path: str, content_type: str
    ) -> dict:
        """Generate a v4 signed PUT URL for direct-to-GCS uploads (30-min expiry)."""
        blob = self.bucket.blob(destination_path)

        from google.auth.transport import requests

        request = requests.Request()
        self.credentials.refresh(request)

        upload_expiry = timedelta(minutes=30)
        expires_at = datetime.now(timezone.utc) + upload_expiry
        url = blob.generate_signed_url(
            version="v4",
            expiration=upload_expiry,
            method="PUT",
            content_type=content_type,
            service_account_email=self.credentials.service_account_email,
            access_token=self.credentials.token,
        )
        return {
            "upload_url": url,
            "gcs_uri": f"gs://{self.bucket_name}/{destination_path}",
            "expires_at": expires_at.isoformat(),
        }

    def blob_exists(self, gcs_uri: str) -> bool:
        """Check whether a blob exists in GCS."""
        path = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
        return self.bucket.blob(path).exists()

    def resolve_cached_url(self, gcs_uri: str, cache: dict) -> tuple[str, bool]:
        """Return (signed_url, changed) using cache. Only re-signs if close to expiry."""
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri or "", False

        cached = cache.get(gcs_uri)
        if cached and cached.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if expires_at - datetime.now(timezone.utc) > REFRESH_THRESHOLD:
                    return cached["url"], False
            except (ValueError, TypeError):
                pass

        entry = self._generate_signed_url(gcs_uri)
        cache[gcs_uri] = entry
        return entry["url"], True

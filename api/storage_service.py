import os
import google.auth
from datetime import timedelta
from google.cloud import storage

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
            # Only try to create if it doesn't exist, not if we lack permissions
            # If the error is 'Not Found', try creating. Otherwise, raise.
            if "404" in str(e):
                try:
                    self.bucket = self.client.create_bucket(self.bucket_name)
                except Exception as create_error:
                    print(f"Failed to create bucket '{self.bucket_name}': {create_error}")
                    raise
            else:
                print(f"Failed to access bucket '{self.bucket_name}': {e}")
                raise

    def upload_file(self, content: bytes, destination_path: str, content_type: str) -> str:
        blob = self.bucket.blob(destination_path)
        blob.upload_from_string(content, content_type=content_type)
        return f"gs://{self.bucket_name}/{destination_path}"

    def get_signed_url(self, gcs_uri: str) -> str:
        if not gcs_uri.startswith("gs://"):
            return gcs_uri
        
        path = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
        blob = self.bucket.blob(path)
        
        # Refresh credentials to ensure we have a valid token
        from google.auth.transport import requests
        request = requests.Request()
        self.credentials.refresh(request)

        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(minutes=60),
            method="GET",
            service_account_email=self.credentials.service_account_email,
            access_token=self.credentials.token
        )

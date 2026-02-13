from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class StitchRequest(BaseModel):
    manifest_gcs_uri: str
    output_gcs_uri: str
    project_id: str
    location: str = "us-central1"

class JobStatus(BaseModel):
    job_id: str
    status: str
    manifest_gcs_uri: str
    output_gcs_uri: str
    transcoder_job_name: Optional[str] = None
    last_updated: datetime
    error_message: Optional[str] = None

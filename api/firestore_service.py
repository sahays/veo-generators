from typing import Optional
from google.cloud import firestore
from datetime import datetime
from models import JobStatus

class FirestoreService:
    def __init__(self, collection_name="veogen_jobs"):
        self.db = firestore.Client()
        self.collection = self.db.collection(collection_name)

    def get_job(self, job_id: str) -> Optional[JobStatus]:
        doc = self.collection.document(job_id).get()
        if doc.exists:
            data = doc.to_dict()
            return JobStatus(**data)
        return None

    def update_job(self, job: JobStatus):
        job.last_updated = datetime.utcnow()
        self.collection.document(job.job_id).set(job.dict())

    def delete_job(self, job_id: str):
        self.collection.document(job_id).delete()

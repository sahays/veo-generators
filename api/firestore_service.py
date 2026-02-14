import os
from typing import List, Optional
from google.cloud import firestore
from datetime import datetime
from models import Project, ProjectStatus

class FirestoreService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        collection_name = os.getenv("FIRESTORE_COLLECTION", "veogen_projects")
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(collection_name)

    def get_projects(self) -> List[Project]:
        docs = self.collection.order_by("created_at", direction=firestore.Query.DESCENDING).stream()
        return [Project(**doc.to_dict()) for doc in docs]

    def get_project(self, project_id: str) -> Optional[Project]:
        doc = self.collection.document(project_id).get()
        if doc.exists:
            return Project(**doc.to_dict())
        return None

    def create_project(self, project: Project):
        self.collection.document(project.id).set(project.dict())

    def update_project(self, project_id: str, updates: dict):
        updates["updated_at"] = datetime.utcnow()
        self.collection.document(project_id).update(updates)

    def delete_project(self, project_id: str):
        self.collection.document(project_id).delete()

    def set_config_options(self, category: str, options: List[str]):
        self.db.collection("configs").document(category).set({"options": options})

    def get_config_options(self, category: str) -> List[str]:
        doc = self.db.collection("configs").document(category).get()
        if doc.exists:
            return doc.to_dict().get("options", [])
        return []

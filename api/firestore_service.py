import os
from typing import List, Optional
from google.cloud import firestore
from datetime import datetime
from models import Project, ProjectStatus

class FirestoreService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        collection_name = os.getenv("FIRESTORE_COLLECTION", "productions")
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(collection_name)

    def get_productions(self) -> List[Project]:
        docs = self.collection.order_by("createdAt", direction=firestore.Query.DESCENDING).stream()
        return [Project(**doc.to_dict()) for doc in docs]

    def get_production(self, production_id: str) -> Optional[Project]:
        doc = self.collection.document(production_id).get()
        if doc.exists:
            return Project(**doc.to_dict())
        return None

    def create_production(self, production: Project):
        self.collection.document(production.id).set(production.dict())

    def update_production(self, production_id: str, updates: dict):
        updates["updatedAt"] = datetime.utcnow()
        if "status" in updates and isinstance(updates["status"], ProjectStatus):
            updates["status"] = updates["status"].value
        self.collection.document(production_id).update(updates)

    def delete_production(self, production_id: str):
        self.collection.document(production_id).delete()

    def update_scene(self, production_id: str, scene_id: str, updates: dict):
        production = self.get_production(production_id)
        if not production:
            return
        
        updated_scenes = []
        for scene in production.scenes:
            if scene.id == scene_id:
                scene_dict = scene.dict()
                scene_dict.update(updates)
                updated_scenes.append(scene_dict)
            else:
                updated_scenes.append(scene.dict())
        
        self.update_production(production_id, {"scenes": updated_scenes})

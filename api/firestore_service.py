import os
from typing import List, Optional
from google.cloud import firestore
from datetime import datetime
from models import Project, ProjectStatus, SystemResource


class FirestoreService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        collection_name = os.getenv("FIRESTORE_COLLECTION", "productions")
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(collection_name)
        self.resources_collection = self.db.collection("system_resources")

    def list_resources(
        self, resource_type: Optional[str] = None, category: Optional[str] = None
    ) -> List[SystemResource]:
        query = self.resources_collection
        if resource_type:
            query = query.where("type", "==", resource_type)
        if category:
            query = query.where("category", "==", category)

        docs = query.order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        ).stream()
        return [SystemResource(**doc.to_dict()) for doc in docs]

    def get_resource(self, resource_id: str) -> Optional[SystemResource]:
        doc = self.resources_collection.document(resource_id).get()
        if doc.exists:
            return SystemResource(**doc.to_dict())
        return None

    def get_active_resource(
        self, resource_type: str, category: str
    ) -> Optional[SystemResource]:
        query = (
            self.resources_collection.where("type", "==", resource_type)
            .where("category", "==", category)
            .where("is_active", "==", True)
            .limit(1)
        )

        docs = list(query.stream())
        if docs:
            return SystemResource(**docs[0].to_dict())
        return None

    def create_resource(self, resource: SystemResource):
        self.resources_collection.document(resource.id).set(resource.dict())

    def set_resource_active(self, resource_id: str):
        resource = self.get_resource(resource_id)
        if not resource:
            return

        # Deactivate current active in same type/category
        actives = (
            self.resources_collection.where("type", "==", resource.type)
            .where("category", "==", resource.category)
            .where("is_active", "==", True)
            .stream()
        )

        batch = self.db.batch()
        for doc in actives:
            batch.update(doc.reference, {"is_active": False})

        # Activate target
        batch.update(
            self.resources_collection.document(resource_id), {"is_active": True}
        )
        batch.commit()

    def get_productions(self) -> List[Project]:
        docs = self.collection.order_by(
            "createdAt", direction=firestore.Query.DESCENDING
        ).stream()
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

import os
from typing import List, Optional
from google.cloud import firestore
from datetime import datetime
from models import Project, ProjectStatus, SystemResource


class FirestoreService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        service_name = os.getenv("SERVICE_NAME", "veo-generators")
        prefix = service_name.replace("-", "_")
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(f"{prefix}_productions")
        self.resources_collection = self.db.collection(f"{prefix}_prompts")

    def _all_resources(self) -> List[SystemResource]:
        docs = self.resources_collection.stream()
        resources = [SystemResource(**doc.to_dict()) for doc in docs]
        resources.sort(key=lambda r: r.createdAt or "", reverse=True)
        return resources

    def list_resources(
        self, resource_type: Optional[str] = None, category: Optional[str] = None
    ) -> List[SystemResource]:
        resources = self._all_resources()
        if resource_type:
            resources = [r for r in resources if r.type == resource_type]
        if category:
            resources = [r for r in resources if r.category == category]
        return resources

    def get_resource(self, resource_id: str) -> Optional[SystemResource]:
        doc = self.resources_collection.document(resource_id).get()
        if doc.exists:
            return SystemResource(**doc.to_dict())
        return None

    def get_active_resource(
        self, resource_type: str, category: str
    ) -> Optional[SystemResource]:
        resources = self._all_resources()
        for r in resources:
            if r.type == resource_type and r.category == category and r.is_active:
                return r
        return None

    def create_resource(self, resource: SystemResource):
        self.resources_collection.document(resource.id).set(resource.dict())

    def set_resource_active(self, resource_id: str):
        resource = self.get_resource(resource_id)
        if not resource:
            return

        # Deactivate current active in same type/category, activate target
        all_resources = self._all_resources()
        batch = self.db.batch()
        for r in all_resources:
            if (
                r.type == resource.type
                and r.category == resource.category
                and r.is_active
            ):
                batch.update(
                    self.resources_collection.document(r.id), {"is_active": False}
                )
        batch.update(
            self.resources_collection.document(resource_id), {"is_active": True}
        )
        batch.commit()

    def get_productions(self, include_archived: bool = False) -> List[Project]:
        docs = self.collection.stream()
        productions = [Project(**doc.to_dict()) for doc in docs]
        productions.sort(key=lambda p: p.createdAt or "", reverse=True)
        if not include_archived:
            productions = [p for p in productions if not p.archived]
        return productions

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

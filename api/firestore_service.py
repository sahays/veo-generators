import os
from typing import List, Optional
from google.cloud import firestore
from datetime import datetime
from models import (
    Project,
    ProjectStatus,
    SystemResource,
    KeyMomentsRecord,
    ThumbnailRecord,
    UploadRecord,
    InviteCode,
    ReframeRecord,
    PromoRecord,
)


class FirestoreService:
    def __init__(self):
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        service_name = os.getenv("SERVICE_NAME", "veo-generators")
        prefix = service_name.replace("-", "_")
        self.db = firestore.Client(project=project_id)
        self.collection = self.db.collection(f"{prefix}_productions")
        self.resources_collection = self.db.collection(f"{prefix}_prompts")
        self.key_moments_collection = self.db.collection(f"{prefix}_key_moments")
        self.thumbnails_collection = self.db.collection(f"{prefix}_thumbnails")
        self.uploads_collection = self.db.collection(f"{prefix}_uploads")
        self.invite_codes_collection = self.db.collection(f"{prefix}_invite_codes")
        self.reframe_collection = self.db.collection(f"{prefix}_reframes")
        self.promo_collection = self.db.collection(f"{prefix}_promos")

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

    # --- Key Moments ---

    def get_key_moments_analyses(
        self, include_archived: bool = False
    ) -> List[KeyMomentsRecord]:
        docs = self.key_moments_collection.stream()
        records = [KeyMomentsRecord(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not r.archived]
        return records

    def get_key_moments_analysis(self, record_id: str) -> Optional[KeyMomentsRecord]:
        doc = self.key_moments_collection.document(record_id).get()
        if doc.exists:
            return KeyMomentsRecord(**doc.to_dict())
        return None

    def create_key_moments_analysis(self, record: KeyMomentsRecord):
        self.key_moments_collection.document(record.id).set(record.dict())

    def delete_key_moments_analysis(self, record_id: str):
        self.key_moments_collection.document(record_id).delete()

    # --- Thumbnails ---

    def get_thumbnail_records(
        self, include_archived: bool = False
    ) -> List[ThumbnailRecord]:
        docs = self.thumbnails_collection.stream()
        records = [ThumbnailRecord(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not r.archived]
        return records

    def get_thumbnail_record(self, record_id: str) -> Optional[ThumbnailRecord]:
        doc = self.thumbnails_collection.document(record_id).get()
        if doc.exists:
            return ThumbnailRecord(**doc.to_dict())
        return None

    def create_thumbnail_record(self, record: ThumbnailRecord):
        self.thumbnails_collection.document(record.id).set(record.dict())

    def update_thumbnail_record(self, record_id: str, updates: dict):
        self.thumbnails_collection.document(record_id).update(updates)

    def delete_thumbnail_record(self, record_id: str):
        self.thumbnails_collection.document(record_id).delete()

    # --- Reframes ---

    def get_reframe_records(
        self, include_archived: bool = False
    ) -> List[ReframeRecord]:
        docs = self.reframe_collection.stream()
        records = [ReframeRecord(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not r.archived]
        return records

    def get_reframe_record(self, record_id: str) -> Optional[ReframeRecord]:
        doc = self.reframe_collection.document(record_id).get()
        if doc.exists:
            return ReframeRecord(**doc.to_dict())
        return None

    def create_reframe_record(self, record: ReframeRecord):
        self.reframe_collection.document(record.id).set(record.dict())

    def update_reframe_record(self, record_id: str, updates: dict):
        self.reframe_collection.document(record_id).update(updates)

    def delete_reframe_record(self, record_id: str):
        self.reframe_collection.document(record_id).delete()

    # --- Promos ---

    def get_promo_records(self, include_archived: bool = False) -> List[PromoRecord]:
        docs = self.promo_collection.stream()
        records = [PromoRecord(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not r.archived]
        return records

    def get_promo_record(self, record_id: str) -> Optional[PromoRecord]:
        doc = self.promo_collection.document(record_id).get()
        if doc.exists:
            return PromoRecord(**doc.to_dict())
        return None

    def create_promo_record(self, record: PromoRecord):
        self.promo_collection.document(record.id).set(record.dict())

    def update_promo_record(self, record_id: str, updates: dict):
        self.promo_collection.document(record_id).update(updates)

    def delete_promo_record(self, record_id: str):
        self.promo_collection.document(record_id).delete()

    # --- Uploads ---

    def get_upload_records(
        self,
        include_archived: bool = False,
        file_type: Optional[str] = None,
        include_pending: bool = False,
    ) -> List[UploadRecord]:
        docs = self.uploads_collection.stream()
        records = [UploadRecord(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not r.archived]
        if not include_pending:
            records = [r for r in records if r.status != "pending"]
        if file_type:
            records = [r for r in records if r.file_type == file_type]
        return records

    def get_upload_record(self, record_id: str) -> Optional[UploadRecord]:
        doc = self.uploads_collection.document(record_id).get()
        if doc.exists:
            return UploadRecord(**doc.to_dict())
        return None

    def create_upload_record(self, record: UploadRecord):
        self.uploads_collection.document(record.id).set(record.dict())

    def update_upload_record(self, record_id: str, updates: dict):
        self.uploads_collection.document(record_id).update(updates)

    def delete_upload_record(self, record_id: str):
        self.uploads_collection.document(record_id).delete()

    # --- Invite Codes ---

    def get_invite_codes(self) -> List[InviteCode]:
        docs = self.invite_codes_collection.stream()
        codes = [InviteCode(**doc.to_dict()) for doc in docs]
        codes.sort(key=lambda c: c.createdAt or "", reverse=True)
        return codes

    def get_invite_code(self, code_id: str) -> Optional[InviteCode]:
        doc = self.invite_codes_collection.document(code_id).get()
        if doc.exists:
            return InviteCode(**doc.to_dict())
        return None

    def get_invite_code_by_value(self, code_str: str) -> Optional[InviteCode]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = self.invite_codes_collection.where(
            filter=FieldFilter("code", "==", code_str)
        ).stream()
        for doc in docs:
            return InviteCode(**doc.to_dict())
        return None

    def create_invite_code(self, invite_code: InviteCode):
        self.invite_codes_collection.document(invite_code.id).set(invite_code.dict())

    def update_invite_code(self, code_id: str, updates: dict):
        self.invite_codes_collection.document(code_id).update(updates)

    def delete_invite_code(self, code_id: str):
        self.invite_codes_collection.document(code_id).delete()

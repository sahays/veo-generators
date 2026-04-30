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
    AdaptRecord,
    AIModel,
    Avatar,
    AvatarTurn,
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
        self.adapts_collection = self.db.collection(f"{prefix}_adapts")
        self.models_collection = self.db.collection(f"{prefix}_models")
        self.avatars_collection = self.db.collection(f"{prefix}_avatars")
        self.avatar_turns_collection = self.db.collection(f"{prefix}_avatar_turns")

    # --- Generic CRUD helpers ---

    def _get_records(self, collection, model_cls, include_archived=False):
        docs = collection.stream()
        records = [model_cls(**doc.to_dict()) for doc in docs]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        if not include_archived:
            records = [r for r in records if not getattr(r, "archived", False)]
        return records

    def _get_record(self, collection, model_cls, record_id):
        doc = collection.document(record_id).get()
        if doc.exists:
            return model_cls(**doc.to_dict())
        return None

    def _create_record(self, collection, record):
        collection.document(record.id).set(record.dict())

    def _update_record(self, collection, record_id, updates):
        collection.document(record_id).update(updates)

    def _delete_record(self, collection, record_id):
        collection.document(record_id).delete()

    def _all_resources(self) -> List[SystemResource]:
        return self._get_records(
            self.resources_collection, SystemResource, include_archived=True
        )

    def list_resources(
        self, resource_type: Optional[str] = None, category: Optional[str] = None
    ) -> List[SystemResource]:
        # Push the type filter to Firestore (single-field indexes are auto).
        # Category stays Python-side to avoid forcing a composite index.
        query = self.resources_collection
        if resource_type:
            query = query.where("type", "==", resource_type)
        records = [SystemResource(**doc.to_dict()) for doc in query.stream()]
        records.sort(key=lambda r: r.createdAt or "", reverse=True)
        records = [r for r in records if not getattr(r, "archived", False)]
        if category:
            records = [r for r in records if r.category == category]
        return records

    def get_resource(self, resource_id: str) -> Optional[SystemResource]:
        return self._get_record(self.resources_collection, SystemResource, resource_id)

    def get_active_resource(
        self, resource_type: str, category: str
    ) -> Optional[SystemResource]:
        resources = self._all_resources()
        for r in resources:
            if r.type == resource_type and r.category == category and r.is_active:
                return r
        return None

    def create_resource(self, resource: SystemResource):
        self._create_record(self.resources_collection, resource)

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
        return self._get_records(self.collection, Project, include_archived)

    def get_production(self, production_id: str) -> Optional[Project]:
        return self._get_record(self.collection, Project, production_id)

    def create_production(self, production: Project):
        self._create_record(self.collection, production)

    def update_production(self, production_id: str, updates: dict):
        updates["updatedAt"] = datetime.utcnow()
        if "status" in updates and isinstance(updates["status"], ProjectStatus):
            updates["status"] = updates["status"].value
        self._update_record(self.collection, production_id, updates)

    def delete_production(self, production_id: str):
        self._delete_record(self.collection, production_id)

    def update_scene(self, production_id: str, scene_id: str, updates: dict):
        production = self.get_production(production_id)
        if not production:
            return
        # Dict-by-id mutation: O(n) once instead of branching per scene.
        scenes_by_id = {s.id: s.dict() for s in production.scenes}
        target = scenes_by_id.get(scene_id)
        if not target:
            return
        target.update(updates)
        self.update_production(production_id, {"scenes": list(scenes_by_id.values())})

    # --- Key Moments ---

    def get_key_moments_analyses(
        self, include_archived: bool = False
    ) -> List[KeyMomentsRecord]:
        return self._get_records(
            self.key_moments_collection, KeyMomentsRecord, include_archived
        )

    def get_key_moments_analysis(self, record_id: str) -> Optional[KeyMomentsRecord]:
        return self._get_record(
            self.key_moments_collection, KeyMomentsRecord, record_id
        )

    def create_key_moments_analysis(self, record: KeyMomentsRecord):
        self._create_record(self.key_moments_collection, record)

    def update_key_moments_analysis(self, record_id: str, updates: dict):
        self._update_record(self.key_moments_collection, record_id, updates)

    def delete_key_moments_analysis(self, record_id: str):
        self._delete_record(self.key_moments_collection, record_id)

    # --- Thumbnails ---

    def get_thumbnail_records(
        self, include_archived: bool = False
    ) -> List[ThumbnailRecord]:
        return self._get_records(
            self.thumbnails_collection, ThumbnailRecord, include_archived
        )

    def get_thumbnail_record(self, record_id: str) -> Optional[ThumbnailRecord]:
        return self._get_record(self.thumbnails_collection, ThumbnailRecord, record_id)

    def create_thumbnail_record(self, record: ThumbnailRecord):
        self._create_record(self.thumbnails_collection, record)

    def update_thumbnail_record(self, record_id: str, updates: dict):
        self._update_record(self.thumbnails_collection, record_id, updates)

    def delete_thumbnail_record(self, record_id: str):
        self._delete_record(self.thumbnails_collection, record_id)

    # --- Reframes ---

    def get_reframe_records(
        self, include_archived: bool = False
    ) -> List[ReframeRecord]:
        return self._get_records(
            self.reframe_collection, ReframeRecord, include_archived
        )

    def get_reframe_record(self, record_id: str) -> Optional[ReframeRecord]:
        return self._get_record(self.reframe_collection, ReframeRecord, record_id)

    def create_reframe_record(self, record: ReframeRecord):
        self._create_record(self.reframe_collection, record)

    def update_reframe_record(self, record_id: str, updates: dict):
        self._update_record(self.reframe_collection, record_id, updates)

    def delete_reframe_record(self, record_id: str):
        self._delete_record(self.reframe_collection, record_id)

    # --- Promos ---

    def get_promo_records(self, include_archived: bool = False) -> List[PromoRecord]:
        return self._get_records(self.promo_collection, PromoRecord, include_archived)

    def get_promo_record(self, record_id: str) -> Optional[PromoRecord]:
        return self._get_record(self.promo_collection, PromoRecord, record_id)

    def create_promo_record(self, record: PromoRecord):
        self._create_record(self.promo_collection, record)

    def update_promo_record(self, record_id: str, updates: dict):
        self._update_record(self.promo_collection, record_id, updates)

    def delete_promo_record(self, record_id: str):
        self._delete_record(self.promo_collection, record_id)

    # --- Adapts ---

    def get_adapt_records(self, include_archived: bool = False) -> List[AdaptRecord]:
        return self._get_records(self.adapts_collection, AdaptRecord, include_archived)

    def get_adapt_record(self, record_id: str) -> Optional[AdaptRecord]:
        return self._get_record(self.adapts_collection, AdaptRecord, record_id)

    def create_adapt_record(self, record: AdaptRecord):
        self._create_record(self.adapts_collection, record)

    def update_adapt_record(self, record_id: str, updates: dict):
        self._update_record(self.adapts_collection, record_id, updates)

    def delete_adapt_record(self, record_id: str):
        self._delete_record(self.adapts_collection, record_id)

    # --- Uploads ---

    def get_upload_records(
        self,
        include_archived: bool = False,
        file_type: Optional[str] = None,
        include_pending: bool = False,
    ) -> List[UploadRecord]:
        records = self._get_records(
            self.uploads_collection, UploadRecord, include_archived
        )
        if not include_pending:
            records = [r for r in records if r.status != "pending"]
        if file_type:
            records = [r for r in records if r.file_type == file_type]
        return records

    def get_upload_record(self, record_id: str) -> Optional[UploadRecord]:
        return self._get_record(self.uploads_collection, UploadRecord, record_id)

    def create_upload_record(self, record: UploadRecord):
        self._create_record(self.uploads_collection, record)

    def update_upload_record(self, record_id: str, updates: dict):
        self._update_record(self.uploads_collection, record_id, updates)

    def delete_upload_record(self, record_id: str):
        self._delete_record(self.uploads_collection, record_id)

    # --- Invite Codes ---

    def get_invite_codes(self) -> List[InviteCode]:
        return self._get_records(
            self.invite_codes_collection, InviteCode, include_archived=True
        )

    def get_invite_code(self, code_id: str) -> Optional[InviteCode]:
        return self._get_record(self.invite_codes_collection, InviteCode, code_id)

    def get_invite_code_by_value(self, code_str: str) -> Optional[InviteCode]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = self.invite_codes_collection.where(
            filter=FieldFilter("code", "==", code_str)
        ).stream()
        for doc in docs:
            return InviteCode(**doc.to_dict())
        return None

    def create_invite_code(self, invite_code: InviteCode):
        self._create_record(self.invite_codes_collection, invite_code)

    def update_invite_code(self, code_id: str, updates: dict):
        self._update_record(self.invite_codes_collection, code_id, updates)

    def delete_invite_code(self, code_id: str):
        self._delete_record(self.invite_codes_collection, code_id)

    # --- AI Models ---

    def get_ai_models(self) -> List[AIModel]:
        return self._get_records(self.models_collection, AIModel, include_archived=True)

    def get_ai_model(self, model_id: str) -> Optional[AIModel]:
        return self._get_record(self.models_collection, AIModel, model_id)

    def create_ai_model(self, model: AIModel):
        self._create_record(self.models_collection, model)

    def update_ai_model(self, model_id: str, updates: dict):
        self._update_record(self.models_collection, model_id, updates)

    def delete_ai_model(self, model_id: str):
        self._delete_record(self.models_collection, model_id)

    def get_default_model(self, capability: str) -> Optional[AIModel]:
        models = self.get_ai_models()
        for m in models:
            if m.capability == capability and m.is_default and m.is_active:
                return m
        return None

    def set_model_default(self, model_id: str):
        model = self.get_ai_model(model_id)
        if not model:
            return
        all_models = self.get_ai_models()
        batch = self.db.batch()
        for m in all_models:
            if m.capability == model.capability and m.is_default:
                batch.update(
                    self.models_collection.document(m.id), {"is_default": False}
                )
        batch.update(self.models_collection.document(model_id), {"is_default": True})
        batch.commit()

    # --- Avatars ---

    def get_avatars(self, include_archived: bool = False) -> List[Avatar]:
        return self._get_records(self.avatars_collection, Avatar, include_archived)

    def get_avatar(self, avatar_id: str) -> Optional[Avatar]:
        return self._get_record(self.avatars_collection, Avatar, avatar_id)

    def create_avatar(self, avatar: Avatar):
        self._create_record(self.avatars_collection, avatar)

    def update_avatar(self, avatar_id: str, updates: dict):
        self._update_record(self.avatars_collection, avatar_id, updates)

    def delete_avatar(self, avatar_id: str):
        self._delete_record(self.avatars_collection, avatar_id)

    # --- Avatar Turns ---

    def get_avatar_turns(
        self, avatar_id: Optional[str] = None, include_archived: bool = False
    ) -> List[AvatarTurn]:
        records = self._get_records(
            self.avatar_turns_collection, AvatarTurn, include_archived
        )
        if avatar_id:
            records = [r for r in records if r.avatar_id == avatar_id]
        return records

    def get_pending_avatar_turns(self) -> List[AvatarTurn]:
        records = self._get_records(
            self.avatar_turns_collection, AvatarTurn, include_archived=False
        )
        return [r for r in records if r.status == "pending"]

    def reclaim_orphan_avatar_turns(self) -> int:
        """Flip any `generating` avatar turns back to `pending`.

        Called on worker startup so a turn that was being rendered when the
        previous worker died can be re-picked. Safe under single-instance
        worker config (only one worker ever processes turns).
        Returns the count of reclaimed turns.
        """
        records = self._get_records(
            self.avatar_turns_collection, AvatarTurn, include_archived=False
        )
        orphans = [r for r in records if r.status == "generating"]
        for r in orphans:
            self._update_record(
                self.avatar_turns_collection,
                r.id,
                {"status": "pending", "progress_pct": 0},
            )
        return len(orphans)

    def get_avatar_turn(self, turn_id: str) -> Optional[AvatarTurn]:
        return self._get_record(self.avatar_turns_collection, AvatarTurn, turn_id)

    def create_avatar_turn(self, turn: AvatarTurn):
        self._create_record(self.avatar_turns_collection, turn)

    def update_avatar_turn(self, turn_id: str, updates: dict):
        self._update_record(self.avatar_turns_collection, turn_id, updates)

    def delete_avatar_turn(self, turn_id: str):
        self._delete_record(self.avatar_turns_collection, turn_id)

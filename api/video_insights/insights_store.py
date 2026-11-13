"""Firestore accessors for scene analysis and engagement records.

Mixed into `FirestoreService`, which supplies the collections and the generic
`_get_records` / `_get_record` / `_create_record` / `_update_record` /
`_delete_record` helpers used here.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from models import EngagementRecord, SceneAnalysisRecord
from models_insights import TIMELINE_SCHEMA_VERSION

_REUSABLE_STATUSES = frozenset({"pending", "analyzing", "processing", "completed"})


class InsightsStoreMixin:
    """Scene analysis + engagement persistence for `FirestoreService`."""

    scene_analyses_collection: Any
    engagements_collection: Any
    _get_records: Callable[..., list]
    _get_record: Callable[..., Any]
    _create_record: Callable[..., None]
    _update_record: Callable[..., None]
    _delete_record: Callable[..., None]

    # --- Scene analyses ---

    def get_scene_analyses(
        self, include_archived: bool = False
    ) -> List[SceneAnalysisRecord]:
        return self._get_records(
            self.scene_analyses_collection, SceneAnalysisRecord, include_archived
        )

    def get_scene_analysis(self, record_id: str) -> Optional[SceneAnalysisRecord]:
        return self._get_record(
            self.scene_analyses_collection, SceneAnalysisRecord, record_id
        )

    def create_scene_analysis(self, record: SceneAnalysisRecord) -> None:
        self._create_record(self.scene_analyses_collection, record)

    def update_scene_analysis(self, record_id: str, updates: dict) -> None:
        self._update_record(self.scene_analyses_collection, record_id, updates)

    def delete_scene_analysis(self, record_id: str) -> None:
        self._delete_record(self.scene_analyses_collection, record_id)

    def find_reusable_scene_analysis(
        self, source_type: str, source_id: str
    ) -> Optional[SceneAnalysisRecord]:
        """Newest live analysis of a source on the current timeline schema.

        Engagement reuses it instead of analysing the same video again. Uses a
        single-field equality query, so no composite index is required.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = self.scene_analyses_collection.where(
            filter=FieldFilter("source_id", "==", source_id)
        ).stream()
        candidates = [SceneAnalysisRecord(**doc.to_dict()) for doc in docs]
        usable = [
            r
            for r in candidates
            if r.source_type == source_type
            and not r.archived
            and r.status in _REUSABLE_STATUSES
            and r.schema_version == TIMELINE_SCHEMA_VERSION
        ]
        return max(usable, key=lambda r: r.createdAt, default=None)

    # --- Engagements ---

    def get_engagements(self, include_archived: bool = False) -> List[EngagementRecord]:
        return self._get_records(
            self.engagements_collection, EngagementRecord, include_archived
        )

    def get_engagement(self, record_id: str) -> Optional[EngagementRecord]:
        return self._get_record(
            self.engagements_collection, EngagementRecord, record_id
        )

    def create_engagement(self, record: EngagementRecord) -> None:
        self._create_record(self.engagements_collection, record)

    def update_engagement(self, record_id: str, updates: dict) -> None:
        self._update_record(self.engagements_collection, record_id, updates)

    def delete_engagement(self, record_id: str) -> None:
        self._delete_record(self.engagements_collection, record_id)

    def find_engagements_for_analysis(
        self, scene_analysis_id: str
    ) -> List[EngagementRecord]:
        """Every engagement record built on a scene analysis, archived or not.

        Their workspaces read that analysis's timeline, so it must outlive
        them. Uses a single-field equality query, so no composite index is
        required.
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        docs = self.engagements_collection.where(
            filter=FieldFilter("scene_analysis_id", "==", scene_analysis_id)
        ).stream()
        return [EngagementRecord(**doc.to_dict()) for doc in docs]

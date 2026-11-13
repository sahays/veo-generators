"""Shared fixture for the engagement router tests: the real app over mocked services."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("MASTER_INVITE_CODE", "test-master-code")

BUCKET = "test-bucket"
GUEST_CODE = "engagement-guest-code"
MAX_CSV_BYTES = 10 * 1024 * 1024
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload(uid: str, filename: str, mime: str, **fields: Any) -> Any:
    from models import UploadRecord

    return UploadRecord(
        id=uid,
        filename=filename,
        mime_type=mime,
        gcs_uri=f"gs://{BUCKET}/uploads/{filename}",
        **{"file_type": "other", "file_size_bytes": 2048, **fields},
    )


def _seed_uploads() -> dict[str, Any]:
    uploads = [
        _upload("up-video", "film.mov", "video/quicktime", file_type="video"),
        _upload("up-csv", "ratings.csv", "text/csv"),
        # Windows browsers report CSV files with the Excel MIME type.
        _upload("up-excel-csv", "barc.csv", "application/vnd.ms-excel"),
        _upload("up-xlsx", "barc.xlsx", _XLSX),
        _upload("up-image", "poster.png", "image/png", file_type="image"),
        _upload("up-video-csv", "clip.csv", "video/mp4", file_type="video"),
        _upload("up-pending", "late.csv", "text/csv", status="pending"),
        _upload(
            "up-declared-big", "big.csv", "text/csv", file_size_bytes=MAX_CSV_BYTES + 1
        ),
        # Declared small by the browser, but larger in the bucket.
        _upload("up-stored-big", "grown.csv", "text/csv", file_size_bytes=10),
    ]
    return {upload.id: upload for upload in uploads}


def _guest() -> Any:
    from models_infra import InviteCode

    return InviteCode(
        id="inv-guest",
        code=GUEST_CODE,
        label="guest",
        is_active=True,
        daily_credits=1000,
        expires_at=None,
        createdAt=datetime.now(timezone.utc),
    )


def _wire_firestore(firestore: MagicMock, state: SimpleNamespace) -> None:
    guest = _guest()
    firestore.get_invite_code_by_value.side_effect = {guest.code: guest}.get
    firestore.get_upload_record.side_effect = state.uploads.get
    firestore.get_upload_records.return_value = [state.uploads["up-video"]]
    firestore.get_production.side_effect = {}.get
    firestore.get_productions.return_value = []
    firestore.get_scene_analysis.side_effect = state.analyses.get
    firestore.get_scene_analyses.side_effect = lambda include_archived=False: [
        a for a in state.analyses.values() if include_archived or not a.archived
    ]
    firestore.get_engagement.side_effect = state.engagements.get
    firestore.get_engagements.side_effect = lambda include_archived=False: [
        e for e in state.engagements.values() if include_archived or not e.archived
    ]
    firestore.find_reusable_scene_analysis.return_value = None
    firestore.find_engagements_for_analysis.side_effect = lambda analysis_id: [
        e for e in state.engagements.values() if e.scene_analysis_id == analysis_id
    ]


def _wire_storage(storage: MagicMock, state: SimpleNamespace) -> None:
    storage.resolve_cached_url.side_effect = lambda uri, cache: (f"signed:{uri}", False)
    storage.get_signed_url.side_effect = lambda uri: f"signed:{uri}"
    storage.get_file_size.side_effect = lambda uri: state.sizes.get(uri, 0)
    storage.download_bytes.side_effect = lambda uri: state.blobs[uri]


def _add_analysis(
    state: SimpleNamespace, record_id: str = "sa-1", **fields: Any
) -> Any:
    from models import SceneAnalysisRecord

    record = SceneAnalysisRecord(
        id=record_id,
        **{
            "source_type": "production",
            "source_id": "p-1",
            "video_gcs_uri": f"gs://{BUCKET}/productions/p-1/final.mp4",
            "video_filename": "Diwali Ad.mp4",
            "status": "completed",
            **fields,
        },
    )
    state.analyses[record_id] = record
    return record


def _add_engagement(
    state: SimpleNamespace, record_id: str = "en-1", **fields: Any
) -> Any:
    from models import EngagementRecord

    record = EngagementRecord(
        id=record_id,
        **{
            "scene_analysis_id": "sa-1",
            "source_id": "up-video",
            "video_gcs_uri": f"gs://{BUCKET}/uploads/film.mov",
            **fields,
        },
    )
    state.engagements[record_id] = record
    return record


@pytest.fixture
def engagement_api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """TestClient over the real app with Firestore and GCS mocked.

    `uploads`, `analyses`, `engagements` back the Firestore mock; `sizes` and
    `blobs` (keyed by `gs://` URI) back the storage mock. `add_analysis` and
    `add_engagement` seed a record and return it.
    """
    from fastapi.testclient import TestClient

    import deps
    from main import app

    firestore, storage = MagicMock(), MagicMock()
    state = SimpleNamespace(
        client=TestClient(app),
        firestore=firestore,
        storage=storage,
        uploads=_seed_uploads(),
        analyses={},
        engagements={},
        sizes={f"gs://{BUCKET}/uploads/grown.csv": MAX_CSV_BYTES + 1},
        blobs={},
        master={"X-Invite-Code": os.environ["MASTER_INVITE_CODE"]},
        guest={"X-Invite-Code": GUEST_CODE},
        bucket=BUCKET,
    )
    state.add_analysis = lambda *args, **fields: _add_analysis(state, *args, **fields)
    state.add_engagement = lambda *args, **fields: _add_engagement(
        state, *args, **fields
    )
    _wire_firestore(firestore, state)
    _wire_storage(storage, state)
    monkeypatch.setattr(deps, "firestore_svc", firestore)
    monkeypatch.setattr(deps, "storage_svc", storage)
    return state

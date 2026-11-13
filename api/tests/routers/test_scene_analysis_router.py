"""Scene analysis router: create validation, source resolution, access, assets."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("MASTER_INVITE_CODE", "test-master-code")
MASTER = {"X-Invite-Code": os.environ["MASTER_INVITE_CODE"]}
GUEST = {"X-Invite-Code": "sa-guest-code"}
BASE = "/api/v1/scene-analysis"
BUCKET = "test-bucket"
SECRET = "service-account-key-0xDEADBEEF"


def _recover(url: str) -> Optional[str]:
    """Mirror of StorageService.recover_gcs_uri for the test bucket."""
    if url.startswith("gs://"):
        return url
    if f"/{BUCKET}/" in url:
        return f"gs://{BUCKET}/" + url.split(f"/{BUCKET}/")[1].split("?")[0]
    return None


def _seed_sources() -> tuple[dict[str, Any], dict[str, Any]]:
    from models import Project, ProjectStatus, UploadRecord

    def upload(uid: str, file_type: str, status: str = "completed") -> UploadRecord:
        mime = "video/quicktime" if file_type == "video" else "image/png"
        return UploadRecord(
            id=uid,
            filename=f"{uid}.mov",
            mime_type=mime,
            file_type=file_type,
            gcs_uri=f"gs://{BUCKET}/uploads/{uid}.mov",
            status=status,
        )

    def production(pid: str, status: ProjectStatus, url: Optional[str]) -> Project:
        return Project(
            id=pid,
            name="Diwali Ad",
            base_concept="x",
            status=status,
            final_video_url=url,
        )

    done, signed = ProjectStatus.COMPLETED, "https://storage.googleapis.com"
    uploads = {
        "up-video": upload("up-video", "video"),
        "up-image": upload("up-image", "image"),
        "up-pending": upload("up-pending", "video", status="pending"),
    }
    productions = {
        "p-gs": production("p-gs", done, f"gs://{BUCKET}/productions/p-gs/final.mp4"),
        "p-https": production(
            "p-https", done, f"{signed}/{BUCKET}/productions/p-https/final.mp4?X-Goog=1"
        ),
        "p-foreign": production("p-foreign", done, f"{signed}/other-bucket/final.mp4"),
        "p-draft": production(
            "p-draft", ProjectStatus.GENERATING, f"gs://{BUCKET}/d.mp4"
        ),
        "p-novideo": production("p-novideo", done, None),
    }
    return uploads, productions


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """TestClient over the real app with Firestore and GCS mocked."""
    from fastapi.testclient import TestClient

    import deps
    from main import app
    from models_infra import InviteCode

    guest = InviteCode(
        id="inv-guest",
        code=GUEST["X-Invite-Code"],
        label="guest",
        is_active=True,
        daily_credits=1000,
        expires_at=None,
        createdAt=datetime.now(timezone.utc),
    )
    uploads, productions = _seed_sources()
    analyses: dict[str, Any] = {}
    firestore, storage = MagicMock(), MagicMock()
    firestore.get_invite_code_by_value.side_effect = {guest.code: guest}.get
    firestore.get_upload_record.side_effect = uploads.get
    firestore.get_upload_records.return_value = [uploads["up-video"]]
    firestore.get_production.side_effect = productions.get
    firestore.get_scene_analysis.side_effect = analyses.get
    firestore.find_engagements_for_analysis.return_value = []
    storage.recover_gcs_uri.side_effect = _recover
    storage.resolve_cached_url.side_effect = lambda uri, cache: (f"signed:{uri}", False)
    storage.get_signed_url.side_effect = lambda uri: f"signed:{uri}"
    monkeypatch.setattr(deps, "firestore_svc", firestore)
    monkeypatch.setattr(deps, "storage_svc", storage)
    return SimpleNamespace(
        client=TestClient(app), firestore=firestore, storage=storage, analyses=analyses
    )


def _analysis(api: SimpleNamespace, record_id: str = "sa-1", **fields: Any) -> Any:
    from models import SceneAnalysisRecord

    record = SceneAnalysisRecord(
        id=record_id,
        source_id="up-video",
        video_gcs_uri=f"gs://{BUCKET}/uploads/up-video.mov",
        **fields,
    )
    api.analyses[record_id] = record
    return record


def _created(api: SimpleNamespace) -> Any:
    return api.firestore.create_scene_analysis.call_args.args[0]


def _post(api: SimpleNamespace, body: dict[str, Any], headers: Any = MASTER) -> Any:
    return api.client.post(BASE, headers=headers, json=body)


# ── Create ───────────────────────────────────────────────────────────


def test_create_from_upload_takes_the_video_location_from_the_stored_record(
    api: SimpleNamespace,
) -> None:
    body = {"source_type": "upload", "source_id": "up-video", "focus": "  the songs "}
    res = _post(api, {**body, "display_name": "Trailer", "model_id": "gemini-x.1"})
    assert res.status_code == 200
    record = _created(api)
    assert res.json() == {"id": record.id, "status": "pending"}
    assert record.video_gcs_uri == f"gs://{BUCKET}/uploads/up-video.mov"
    assert (record.source_type, record.source_id) == ("upload", "up-video")
    assert (record.video_filename, record.mime_type) == (
        "up-video.mov",
        "video/quicktime",
    )
    assert (record.focus, record.display_name, record.model_id) == (
        "the songs",
        "Trailer",
        "gemini-x.1",
    )
    assert record.invite_code == MASTER["X-Invite-Code"]
    assert record.id.startswith("sa-") and record.progress_pct == 0


@pytest.mark.parametrize("field", ["gcs_uri", "video_gcs_uri", "mime_type"])
def test_create_rejects_a_client_supplied_video_location(
    api: SimpleNamespace, field: str
) -> None:
    body = {"source_type": "upload", "source_id": "up-video"}
    res = _post(api, {**body, field: "gs://someone-elses-bucket/private.mp4"})
    assert res.status_code == 422
    api.firestore.create_scene_analysis.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        {"source_id": "up-video"},
        {"source_type": "url", "source_id": "up-video"},
        {"source_type": "upload", "source_id": ""},
        {"source_type": "upload", "source_id": "../../etc/passwd"},
        {"source_type": "upload", "source_id": "up-video", "focus": "x" * 501},
        {"source_type": "upload", "source_id": "up-video", "model_id": "m; rm -rf /"},
    ],
)
def test_create_validates_the_payload(
    api: SimpleNamespace, body: dict[str, Any]
) -> None:
    assert _post(api, body).status_code == 422
    api.firestore.create_scene_analysis.assert_not_called()
    api.firestore.get_upload_record.assert_not_called()


@pytest.mark.parametrize(
    ("source_type", "source_id", "status", "detail"),
    [
        ("upload", "up-missing", 404, "Source not found"),
        ("upload", "up-image", 400, "Source is not a completed video upload"),
        ("upload", "up-pending", 400, "Source is not a completed video upload"),
        ("production", "p-missing", 404, "Source not found"),
        ("production", "p-draft", 400, "Production has no completed final video"),
        ("production", "p-novideo", 400, "Production has no completed final video"),
        ("production", "p-foreign", 400, "Source video is not available"),
        # An upload id is not valid as a production id, and the reverse.
        ("production", "up-video", 404, "Source not found"),
    ],
)
def test_create_fails_for_sources_that_cannot_be_resolved(
    api: SimpleNamespace, source_type: str, source_id: str, status: int, detail: str
) -> None:
    res = _post(api, {"source_type": source_type, "source_id": source_id})
    assert (res.status_code, res.json()) == (status, {"detail": detail})
    api.firestore.create_scene_analysis.assert_not_called()


def test_create_from_production_uses_its_final_video(api: SimpleNamespace) -> None:
    res = _post(api, {"source_type": "production", "source_id": "p-gs"})
    assert res.status_code == 200
    record = _created(api)
    assert record.video_gcs_uri == f"gs://{BUCKET}/productions/p-gs/final.mp4"
    assert (record.source_type, record.video_filename) == (
        "production",
        "Diwali Ad.mp4",
    )


def test_production_https_url_is_converted_back_to_its_gs_uri(
    api: SimpleNamespace,
) -> None:
    res = _post(api, {"source_type": "production", "source_id": "p-https"})
    assert res.status_code == 200
    assert _created(api).video_gcs_uri == f"gs://{BUCKET}/productions/p-https/final.mp4"


# ── Access control ───────────────────────────────────────────────────


def test_guest_cannot_create_retry_or_delete(api: SimpleNamespace) -> None:
    _analysis(api, status="failed")
    body = {"source_type": "upload", "source_id": "up-video"}
    blocked = [
        _post(api, body, headers=GUEST),
        api.client.post(f"{BASE}/sa-1/retry", headers=GUEST),
        api.client.delete(f"{BASE}/sa-1", headers=GUEST),
    ]
    assert [r.status_code for r in blocked] == [403, 403, 403]
    api.firestore.create_scene_analysis.assert_not_called()
    api.firestore.update_scene_analysis.assert_not_called()
    api.firestore.delete_scene_analysis.assert_not_called()
    api.storage.delete_prefix.assert_not_called()


def test_guest_can_read_and_anonymous_callers_are_rejected(
    api: SimpleNamespace,
) -> None:
    _analysis(api)
    assert api.client.get(f"{BASE}/sa-1", headers=GUEST).status_code == 200
    body = {"source_type": "upload", "source_id": "up-video"}
    assert api.client.post(BASE, json=body).status_code == 401
    api.firestore.create_scene_analysis.assert_not_called()


# ── Routing ──────────────────────────────────────────────────────────


def test_source_routes_are_not_captured_by_the_record_id_route(
    api: SimpleNamespace,
) -> None:
    uploads = api.client.get(f"{BASE}/sources/uploads", headers=MASTER)
    assert uploads.status_code == 200
    assert [u["id"] for u in uploads.json()] == ["up-video"]
    assert uploads.json()[0]["video_signed_url"].startswith("signed:gs://")
    api.firestore.get_productions.return_value = []
    productions = api.client.get(f"{BASE}/sources/productions", headers=MASTER)
    assert (productions.status_code, productions.json()) == (200, [])
    api.firestore.get_scene_analysis.assert_not_called()


def test_no_literal_route_is_registered_behind_a_sibling_param_route() -> None:
    from routers import scene_analysis

    param = re.compile(r"^\{[^}]+\}$")
    first_param: dict[tuple, int] = {}
    shadowed, literals = [], []
    for index, route in enumerate(scene_analysis.router.routes):
        segments = [s for s in route.path.split("/") if s]
        for method in route.methods:
            key = ("/".join(segments[:-1]), method, len(segments))
            if param.match(segments[-1]):
                first_param.setdefault(key, index)
            else:
                literals.append(f"{method} {route.path}")
                if key in first_param:
                    shadowed.append(f"{method} {route.path}")
    assert shadowed == []
    assert f"GET {BASE}/sources/uploads" in literals
    assert f"GET {BASE}/{{record_id}}/timeline" in literals


# ── Record responses, retry, delete ──────────────────────────────────


def test_record_response_signs_the_video_and_hides_the_url_cache(
    api: SimpleNamespace,
) -> None:
    _analysis(api, status="analyzing", stage="analyze", stage_detail="window 2 of 5")
    data = api.client.get(f"{BASE}/sa-1", headers=MASTER).json()
    assert data["video_signed_url"] == f"signed:gs://{BUCKET}/uploads/up-video.mov"
    assert (data["stage"], data["stage_detail"]) == ("analyze", "window 2 of 5")
    assert "signed_urls" not in data
    assert api.client.get(f"{BASE}/sa-nope", headers=MASTER).status_code == 404


def test_record_responses_never_expose_the_creators_invite_code(
    api: SimpleNamespace,
) -> None:
    record = _analysis(api, invite_code=SECRET)
    api.firestore.get_scene_analyses.return_value = [record]
    one = api.client.get(f"{BASE}/sa-1", headers=GUEST)
    listed = api.client.get(BASE, headers=GUEST)
    assert (one.status_code, listed.status_code) == (200, 200)
    assert "invite_code" not in one.json()
    assert SECRET not in one.text and SECRET not in listed.text


def test_retry_requeues_a_failed_analysis_and_clears_its_stage(
    api: SimpleNamespace,
) -> None:
    _analysis(
        api, status="failed", stage="analyze", error_message="boom", progress_pct=40
    )
    res = api.client.post(f"{BASE}/sa-1/retry", headers=MASTER)
    assert res.json() == {"id": "sa-1", "status": "pending"}
    api.firestore.update_scene_analysis.assert_called_once_with(
        "sa-1",
        {
            "status": "pending",
            "error_message": None,
            "progress_pct": 0,
            "stage": "",
            "stage_detail": "",
        },
    )


def test_delete_purges_only_the_records_own_prefix(api: SimpleNamespace) -> None:
    _analysis(api, "sa-1")
    _analysis(api, "sa-12")
    res = api.client.delete(f"{BASE}/sa-1", headers=MASTER)
    assert res.json() == {"status": "deleted"}
    # The trailing slash keeps sa-12's objects out of sa-1's purge.
    api.storage.delete_prefix.assert_called_once_with("scene_analysis/sa-1/")
    api.firestore.delete_scene_analysis.assert_called_once_with("sa-1")
    api.storage.delete_blob.assert_not_called()


def test_delete_of_an_unknown_record_purges_nothing(api: SimpleNamespace) -> None:
    res = api.client.delete(f"{BASE}/sa-ghost", headers=MASTER)
    assert res.status_code == 404
    api.storage.delete_prefix.assert_not_called()
    api.firestore.delete_scene_analysis.assert_not_called()


# ── Timeline ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["pending", "analyzing", "processing", "failed"])
def test_timeline_is_409_until_the_analysis_completes(
    api: SimpleNamespace, status: str
) -> None:
    _analysis(api, status=status, timeline_gcs_uri=f"gs://{BUCKET}/stale.json")
    res = api.client.get(f"{BASE}/sa-1/timeline", headers=MASTER)
    assert (res.status_code, res.json()) == (
        409,
        {"detail": "Scene analysis is not completed"},
    )
    api.storage.download_bytes.assert_not_called()


def _completed(api: SimpleNamespace, **fields: Any) -> str:
    uri = f"gs://{BUCKET}/scene_analysis/sa-1/timeline.json"
    _analysis(api, status="completed", timeline_gcs_uri=uri, **fields)
    return uri


def test_timeline_returns_the_document_and_a_signed_filmstrip(
    api: SimpleNamespace,
) -> None:
    from models_insights import FilmstripSpec

    spec = FilmstripSpec(
        tile_width=160, tile_height=90, columns=10, rows=3, interval_sec=2.0, count=30
    )
    strip = f"gs://{BUCKET}/scene_analysis/sa-1/filmstrip.jpg"
    uri = _completed(api, filmstrip=spec, filmstrip_gcs_uri=strip)
    timeline = {"schema_version": "video-timeline-v1", "duration_sec": 60.0, "cues": []}
    api.storage.download_bytes.return_value = json.dumps(timeline).encode()
    res = api.client.get(f"{BASE}/sa-1/timeline", headers=MASTER)
    assert res.status_code == 200
    api.storage.download_bytes.assert_called_once_with(uri)
    assert res.json() == {
        "timeline": timeline,
        "filmstrip": {**spec.model_dump(), "url": f"signed:{strip}"},
    }


def test_timeline_without_a_filmstrip_returns_null_for_it(api: SimpleNamespace) -> None:
    _completed(api)
    api.storage.download_bytes.return_value = b'{"duration_sec": 5.0}'
    res = api.client.get(f"{BASE}/sa-1/timeline", headers=MASTER)
    assert res.json() == {"timeline": {"duration_sec": 5.0}, "filmstrip": None}


@pytest.mark.parametrize("failure", ["storage_error", "not_json"])
def test_timeline_read_failure_is_a_generic_502(
    api: SimpleNamespace, failure: str
) -> None:
    _completed(api)
    if failure == "storage_error":
        api.storage.download_bytes.side_effect = PermissionError(f"denied for {SECRET}")
    else:
        api.storage.download_bytes.return_value = f"<html>{SECRET}</html>".encode()
    res = api.client.get(f"{BASE}/sa-1/timeline", headers=MASTER)
    assert (res.status_code, res.json()) == (502, {"detail": "Timeline is unavailable"})
    assert SECRET not in res.text

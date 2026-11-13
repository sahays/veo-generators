"""Engagement router: create validation, signal and source resolution, access, routing."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any, Optional

import pytest

BASE = "/api/v1/engagement"
TEMPLATE = {"kind": "template", "template_id": "slow_burn"}
BARC = {"kind": "barc", "upload_id": "up-csv"}
FROM_UPLOAD = {"source_type": "upload", "source_id": "up-video"}


def _post(
    api: SimpleNamespace, body: dict[str, Any], headers: Optional[dict] = None
) -> Any:
    return api.client.post(BASE, headers=headers or api.master, json=body)


def _created(api: SimpleNamespace) -> Any:
    return api.firestore.create_engagement.call_args.args[0]


def _assert_nothing_created(api: SimpleNamespace) -> None:
    api.firestore.create_engagement.assert_not_called()
    api.firestore.create_scene_analysis.assert_not_called()


# ── Create: video reference ──────────────────────────────────────────


def test_create_on_a_chosen_analysis_copies_its_source_and_stores_only_the_template(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    analysis = api.add_analysis("sa-1", mime_type="video/webm", status="analyzing")
    body = {"scene_analysis_id": "sa-1", "signal": {**TEMPLATE, "upload_id": "up-csv"}}
    res = _post(api, {**body, "display_name": "  Ep 1 ", "model_id": "gemini-x.1"})
    assert res.status_code == 200
    record = _created(api)
    assert res.json() == {
        "id": record.id,
        "status": "pending",
        "scene_analysis_id": "sa-1",
    }
    assert (record.source_type, record.source_id) == ("production", "p-1")
    assert (record.video_gcs_uri, record.video_filename, record.mime_type) == (
        analysis.video_gcs_uri,
        "Diwali Ad.mp4",
        "video/webm",
    )
    assert (record.display_name, record.model_id) == ("Ep 1", "gemini-x.1")
    assert record.invite_code == api.master["X-Invite-Code"]
    assert record.id.startswith("en-") and record.progress_pct == 0
    # A template signal keeps no CSV fields, even when the client sent some.
    stored = record.signal.model_dump(exclude_defaults=True)
    assert stored == {"template_id": "slow_burn"} and record.signal.kind == "template"
    api.firestore.create_scene_analysis.assert_not_called()
    api.firestore.find_reusable_scene_analysis.assert_not_called()
    api.firestore.get_upload_record.assert_not_called()


def test_create_from_a_source_reuses_a_live_analysis_instead_of_queueing_another(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    live = api.add_analysis(
        "sa-live",
        source_type="upload",
        source_id="up-video",
        video_gcs_uri=f"gs://{api.bucket}/uploads/film.mov",
        status="pending",
    )
    api.firestore.find_reusable_scene_analysis.return_value = live
    res = _post(api, {**FROM_UPLOAD, "signal": TEMPLATE})
    assert res.json()["scene_analysis_id"] == "sa-live"
    api.firestore.find_reusable_scene_analysis.assert_called_once_with(
        "upload", "up-video"
    )
    api.firestore.create_scene_analysis.assert_not_called()
    assert _created(api).scene_analysis_id == "sa-live"


def test_create_from_a_source_queues_one_new_analysis_when_none_is_reusable(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    body = {**FROM_UPLOAD, "signal": TEMPLATE, "display_name": "Report"}
    res = _post(api, {**body, "model_id": "gemini-x.1", "region": "europe-west4"})
    assert res.status_code == 200
    api.firestore.create_scene_analysis.assert_called_once()
    analysis = api.firestore.create_scene_analysis.call_args.args[0]
    record = _created(api)
    assert res.json()["scene_analysis_id"] == analysis.id == record.scene_analysis_id
    assert analysis.id.startswith("sa-") and analysis.status == "pending"
    # The video location comes from the stored upload, for both records.
    uri = f"gs://{api.bucket}/uploads/film.mov"
    assert analysis.video_gcs_uri == record.video_gcs_uri == uri
    assert (analysis.source_type, analysis.source_id) == ("upload", "up-video")
    assert (analysis.model_id, analysis.region) == ("gemini-x.1", "europe-west4")
    assert (analysis.mime_type, record.mime_type) == (
        "video/quicktime",
        "video/quicktime",
    )
    # The report's name is not the analysis's name.
    assert (analysis.display_name, record.display_name) == ("", "Report")


@pytest.mark.parametrize(
    ("fields", "status", "detail"),
    [
        ({"scene_analysis_id": "sa-nope"}, 404, "Scene analysis not found"),
        ({"scene_analysis_id": "sa-archived"}, 400, "Scene analysis is archived"),
        (
            {"scene_analysis_id": "sa-failed"},
            400,
            "Scene analysis failed; retry it or choose another video",
        ),
        (
            {"source_type": "upload", "source_id": "up-image"},
            400,
            "Source is not a completed video upload",
        ),
        ({"source_type": "production", "source_id": "p-none"}, 404, "Source not found"),
    ],
)
def test_create_rejects_a_video_reference_that_cannot_produce_a_timeline(
    engagement_api: SimpleNamespace, fields: dict[str, str], status: int, detail: str
) -> None:
    api = engagement_api
    api.add_analysis("sa-archived", archived=True)
    api.add_analysis("sa-failed", status="failed")
    res = _post(api, {**fields, "signal": TEMPLATE})
    assert (res.status_code, res.json()) == (status, {"detail": detail})
    _assert_nothing_created(api)


# ── Create: signal ───────────────────────────────────────────────────


def test_barc_signal_takes_the_csv_location_and_name_from_the_upload_record(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    signal = {
        **BARC,
        "csv_filename": "../../evil.csv",
        "time_column": "  Time Band ",
        "metric": "TVR",
        "offset_sec": -30.5,
        "template_id": "high",
    }
    res = _post(api, {"scene_analysis_id": "sa-1", "signal": signal})
    assert res.status_code == 200
    assert _created(api).signal.model_dump() == {
        "kind": "barc",
        "template_id": None,
        "upload_id": "up-csv",
        "csv_gcs_uri": f"gs://{api.bucket}/uploads/ratings.csv",
        "csv_filename": "ratings.csv",
        "time_column": "Time Band",
        "metric": "TVR",
        "offset_sec": -30.5,
    }


def test_a_csv_reported_with_the_excel_mime_type_is_accepted_by_its_extension(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    signal = {"kind": "barc", "upload_id": "up-excel-csv"}
    res = _post(api, {"scene_analysis_id": "sa-1", "signal": signal})
    assert res.status_code == 200
    assert _created(api).signal.csv_filename == "barc.csv"


@pytest.mark.parametrize(
    ("upload_id", "status", "detail"),
    [
        ("up-missing", 404, "Signal file not found"),
        ("up-pending", 400, "Signal file upload is not complete"),
        ("up-xlsx", 400, "Signal file must be a CSV file"),
        ("up-image", 400, "Signal file must be a CSV file"),
        # A video is refused whatever its file name says.
        ("up-video-csv", 400, "Signal file must be a CSV file"),
        ("up-declared-big", 400, "The CSV file is larger than the 10 MB limit."),
        ("up-stored-big", 400, "The CSV file is larger than the 10 MB limit."),
    ],
)
def test_an_unusable_signal_upload_fails_before_any_analysis_is_queued(
    engagement_api: SimpleNamespace, upload_id: str, status: int, detail: str
) -> None:
    api = engagement_api
    signal = {"kind": "barc", "upload_id": upload_id}
    res = _post(api, {**FROM_UPLOAD, "signal": signal})
    assert (res.status_code, res.json()) == (status, {"detail": detail})
    _assert_nothing_created(api)
    api.storage.download_bytes.assert_not_called()


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (
            {"scene_analysis_id": "sa-1", **FROM_UPLOAD, "signal": TEMPLATE},
            "Provide either scene_analysis_id, or source_type with source_id",
        ),
        (
            {"signal": TEMPLATE},
            "Provide either scene_analysis_id, or source_type with source_id",
        ),
        (
            {"source_type": "upload", "signal": TEMPLATE},
            "Provide either scene_analysis_id, or source_type with source_id",
        ),
        (
            {"scene_analysis_id": "sa-1", "source_id": "up-video", "signal": TEMPLATE},
            "Provide either scene_analysis_id, or source_type with source_id",
        ),
        (
            {"scene_analysis_id": "sa-1", "signal": {"kind": "template"}},
            "Unknown engagement template",
        ),
        (
            {
                "scene_analysis_id": "sa-1",
                "signal": {"kind": "template", "template_id": "viral"},
            },
            "Unknown engagement template",
        ),
        (
            {"scene_analysis_id": "sa-1", "signal": {"kind": "barc"}},
            "A BARC signal needs upload_id",
        ),
        (
            {"scene_analysis_id": "sa-1", "signal": {**BARC, "offset_sec": 86401}},
            "offset_sec must be within 86400 seconds of zero",
        ),
    ],
)
def test_create_enforces_the_request_rules_before_touching_the_datastore(
    engagement_api: SimpleNamespace, body: dict[str, Any], detail: str
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    res = _post(api, body)
    assert (res.status_code, res.json()) == (400, {"detail": detail})
    _assert_nothing_created(api)
    api.firestore.get_upload_record.assert_not_called()
    api.firestore.get_scene_analysis.assert_not_called()


def test_a_non_finite_offset_is_a_clean_400_not_a_server_error(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    raw = '{"scene_analysis_id": "sa-1", "signal": {"kind": "barc", "upload_id": "up-csv", "offset_sec": NaN}}'
    headers = {**api.master, "Content-Type": "application/json"}
    res = api.client.post(BASE, headers=headers, content=raw)
    assert res.status_code == 400
    assert res.json() == {"detail": "offset_sec must be within 86400 seconds of zero"}
    _assert_nothing_created(api)


@pytest.mark.parametrize(
    "body",
    [
        {"scene_analysis_id": "sa-1"},
        {"scene_analysis_id": "sa-1", "signal": {"kind": "predicted"}},
        {"scene_analysis_id": "../sa-1", "signal": TEMPLATE},
        {"source_type": "url", "source_id": "up-video", "signal": TEMPLATE},
        {"scene_analysis_id": "sa-1", "signal": {**BARC, "upload_id": "a/../b"}},
        {"scene_analysis_id": "sa-1", "signal": TEMPLATE, "model_id": "m; rm -rf /"},
        {"scene_analysis_id": "sa-1", "signal": TEMPLATE, "display_name": "x" * 201},
        # Unknown fields are rejected: the server alone decides where files live.
        {"scene_analysis_id": "sa-1", "signal": TEMPLATE, "video_gcs_uri": "gs://x/y"},
        {
            "scene_analysis_id": "sa-1",
            "signal": {**BARC, "csv_gcs_uri": "gs://someone-elses-bucket/private.csv"},
        },
        {"scene_analysis_id": "sa-1", "signal": {**TEMPLATE, "simulated": False}},
    ],
)
def test_create_rejects_malformed_and_unknown_fields(
    engagement_api: SimpleNamespace, body: dict[str, Any]
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    assert _post(api, body).status_code == 422
    _assert_nothing_created(api)
    api.firestore.get_upload_record.assert_not_called()
    api.firestore.get_scene_analysis.assert_not_called()


# ── Access control ───────────────────────────────────────────────────


def test_guest_cannot_create_preview_retry_or_delete(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    api.add_engagement("en-1", status="failed")
    create = {"scene_analysis_id": "sa-1", "signal": TEMPLATE}
    blocked = [
        _post(api, create, headers=api.guest),
        api.client.post(
            f"{BASE}/signal-preview", headers=api.guest, json={"upload_id": "up-csv"}
        ),
        api.client.post(f"{BASE}/en-1/retry", headers=api.guest),
        api.client.delete(f"{BASE}/en-1", headers=api.guest),
    ]
    assert [r.status_code for r in blocked] == [403, 403, 403, 403]
    _assert_nothing_created(api)
    api.firestore.update_engagement.assert_not_called()
    api.firestore.delete_engagement.assert_not_called()
    api.storage.download_bytes.assert_not_called()
    api.storage.delete_prefix.assert_not_called()


def test_guest_can_read_and_anonymous_callers_are_rejected(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    api.add_engagement("en-1")
    assert api.client.get(f"{BASE}/en-1", headers=api.guest).status_code == 200
    assert api.client.get(f"{BASE}/templates", headers=api.guest).status_code == 200
    body = {"scene_analysis_id": "sa-1", "signal": TEMPLATE}
    assert api.client.post(BASE, json=body).status_code == 401
    assert api.client.get(f"{BASE}/en-1").status_code == 401
    _assert_nothing_created(api)


# ── Routing ──────────────────────────────────────────────────────────


def test_no_literal_route_is_registered_behind_a_sibling_param_route() -> None:
    from routers import engagement

    param = re.compile(r"^\{[^}]+\}$")
    first_param: dict[tuple, int] = {}
    shadowed, literals = [], []
    for index, route in enumerate(engagement.router.routes):
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
    # The check is only meaningful if it saw the routes `/{record_id}` could capture.
    assert {f"GET {BASE}/templates", f"POST {BASE}/signal-preview"} <= set(literals)
    assert first_param[("api/v1/engagement", "GET", 4)] > 0


def test_literal_routes_are_served_by_their_own_handlers(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    templates = api.client.get(f"{BASE}/templates", headers=api.master)
    assert [t["id"] for t in templates.json()] == [
        "high",
        "low",
        "jumpy",
        "slow_burn",
        "front_loaded",
    ]
    assert all(len(t["preview"]) >= 20 and t["label"] for t in templates.json())
    uploads = api.client.get(f"{BASE}/sources/uploads", headers=api.master)
    assert [u["id"] for u in uploads.json()] == ["up-video"]
    productions = api.client.get(f"{BASE}/sources/productions", headers=api.master)
    assert (productions.status_code, productions.json()) == (200, [])
    analyses = api.client.get(f"{BASE}/sources/analyses", headers=api.master)
    assert (analyses.status_code, analyses.json()) == (200, [])
    # None of them fell through to `GET /{record_id}`.
    api.firestore.get_engagement.assert_not_called()

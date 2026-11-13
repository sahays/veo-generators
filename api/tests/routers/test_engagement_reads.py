"""Engagement router: signal preview, analysis picker, report, record lifecycle, pricing."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

BASE = "/api/v1/engagement"
SCENES = "/api/v1/scene-analysis"
SECRET = "service-account-key-0xDEADBEEF"
MAX_CSV_BYTES = 10 * 1024 * 1024
TOO_LARGE = {"detail": "The CSV file is larger than the 10 MB limit."}
CSV = b"Time,TVR %,Reach\n00:00:00,1.2,300\n00:00:30,1.8,340\n00:01:00,0.9,310\n"


def _preview(api: SimpleNamespace, upload_id: str = "up-csv") -> Any:
    body = {"upload_id": upload_id}
    return api.client.post(f"{BASE}/signal-preview", headers=api.master, json=body)


def _csv_uri(api: SimpleNamespace) -> str:
    return f"gs://{api.bucket}/uploads/ratings.csv"


def _broken_parser(*_args: Any) -> dict[str, Any]:
    raise RuntimeError(f"parser bug near {SECRET}")


# ── Signal preview ───────────────────────────────────────────────────


def test_signal_preview_parses_the_csv_the_upload_record_points_at(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.blobs[_csv_uri(api)] = CSV
    res = _preview(api)
    assert res.status_code == 200
    api.storage.download_bytes.assert_called_once_with(_csv_uri(api))
    data = res.json()
    assert (data["filename"], data["row_count"]) == ("ratings.csv", 3)
    assert data["columns"] == ["Time", "TVR %", "Reach"]
    assert (data["time_column"], data["primary_metric"]) == ("Time", "TVR %")
    assert (data["interval_sec"], data["duration_sec"]) == (30.0, 90.0)
    assert data["sample_rows"][0] == {
        "Time": "00:00:00",
        "TVR %": "1.2",
        "Reach": "300",
    }


def test_signal_preview_reports_the_parsers_reason_for_an_unreadable_file(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.blobs[_csv_uri(api)] = b""
    res = _preview(api)
    assert (res.status_code, res.json()) == (400, {"detail": "The CSV file is empty."})


@pytest.mark.parametrize("upload_id", ["up-missing", "up-xlsx", "up-video"])
def test_signal_preview_resolves_the_upload_like_create_does(
    engagement_api: SimpleNamespace, upload_id: str
) -> None:
    api = engagement_api
    res = _preview(api, upload_id)
    assert res.status_code in (400, 404) and res.json()["detail"].startswith("Signal")
    api.storage.download_bytes.assert_not_called()


def test_signal_preview_enforces_the_size_limit_before_downloading(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    res = _preview(api, "up-stored-big")
    assert (res.status_code, res.json()) == (400, TOO_LARGE)
    api.storage.download_bytes.assert_not_called()


def test_signal_preview_enforces_the_size_limit_on_the_bytes_it_received(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    # Object metadata is unavailable (size 0), so only the download reveals the size.
    api.blobs[_csv_uri(api)] = b"t,v\n" + b"1,2\n" * (MAX_CSV_BYTES // 4)
    res = _preview(api)
    assert (res.status_code, res.json()) == (400, TOO_LARGE)


@pytest.mark.parametrize(
    ("failure", "status", "detail"),
    [
        ("storage", 502, "Signal file is unavailable"),
        ("storage_value_error", 502, "Signal file is unavailable"),
        ("parser_bug", 500, "Signal preview failed"),
    ],
)
def test_signal_preview_never_echoes_internal_error_text(
    engagement_api: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    status: int,
    detail: str,
) -> None:
    from routers import engagement

    api = engagement_api
    api.blobs[_csv_uri(api)] = CSV
    if failure == "storage":
        api.storage.download_bytes.side_effect = PermissionError(f"denied {SECRET}")
    elif failure == "storage_value_error":
        # A `ValueError` from storage is not a parser message and must not be shown.
        api.storage.download_bytes.side_effect = ValueError(f"bad blob {SECRET}")
    else:
        monkeypatch.setattr(engagement, "preview_signal_csv", _broken_parser)
    res = _preview(api)
    assert (res.status_code, res.json()) == (status, {"detail": detail})
    assert SECRET not in res.text


# ── Analysis picker ──────────────────────────────────────────────────


def test_analysis_sources_are_live_analyses_newest_first_with_signed_videos(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    now = datetime(2026, 5, 1, 12, 0, 0)
    api.add_analysis("sa-old", createdAt=now - timedelta(days=2), duration_sec=61.5)
    api.add_analysis("sa-new", createdAt=now, status="analyzing", display_name="Ep 2")
    api.add_analysis("sa-mid", createdAt=now - timedelta(days=1), status="failed")
    api.add_analysis("sa-gone", createdAt=now, archived=True)
    api.analyses["sa-new"].invite_code = SECRET
    res = api.client.get(f"{BASE}/sources/analyses", headers=api.master)
    rows = res.json()
    assert [r["id"] for r in rows] == ["sa-new", "sa-mid", "sa-old"]
    assert [r["status"] for r in rows] == ["analyzing", "failed", "completed"]
    assert rows[0] == {
        "id": "sa-new",
        "display_name": "Ep 2",
        "video_filename": "Diwali Ad.mp4",
        "source_type": "production",
        "source_id": "p-1",
        "status": "analyzing",
        "duration_sec": 0.0,
        "createdAt": now.isoformat(),
        "video_signed_url": f"signed:gs://{api.bucket}/productions/p-1/final.mp4",
    }
    assert rows[2]["duration_sec"] == 61.5
    assert SECRET not in res.text


@pytest.mark.parametrize("base", [BASE, SCENES])
def test_production_sources_carry_the_orientation_shown_in_the_picker(
    engagement_api: SimpleNamespace, base: str
) -> None:
    from models import Project, ProjectStatus

    api = engagement_api
    final = f"gs://{api.bucket}/productions/p-1/final.mp4"
    done = {"status": ProjectStatus.COMPLETED, "final_video_url": final}
    api.firestore.get_productions.return_value = [
        Project(id="p-1", name="Reel", base_concept="x", orientation="9:16", **done),
        Project(id="p-2", name="Draft", base_concept="x", orientation="16:9"),
    ]
    rows = api.client.get(f"{base}/sources/productions", headers=api.master).json()
    assert [(r["id"], r["orientation"]) for r in rows] == [("p-1", "9:16")]
    assert rows[0]["video_signed_url"] == f"signed:{final}"


# ── Record responses, retry, delete ──────────────────────────────────


def test_record_response_signs_the_video_and_withholds_internal_fields(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_engagement(
        "en-1", status="pending", stage="waiting", invite_code=SECRET, headline="H"
    )
    data = api.client.get(f"{BASE}/en-1", headers=api.guest).json()
    assert data["video_signed_url"] == f"signed:gs://{api.bucket}/uploads/film.mov"
    assert (data["stage"], data["headline"], data["scene_analysis_id"]) == (
        "waiting",
        "H",
        "sa-1",
    )
    assert "signed_urls" not in data and "invite_code" not in data
    listed = api.client.get(BASE, headers=api.guest)
    api.firestore.get_engagements.assert_called_once_with(include_archived=False)
    assert SECRET not in listed.text
    assert api.client.get(f"{BASE}/en-nope", headers=api.master).status_code == 404


def test_retry_requeues_a_failed_report_and_clears_its_stage(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_engagement("en-1", status="failed", stage="stats", error_message="boom")
    res = api.client.post(f"{BASE}/en-1/retry", headers=api.master)
    assert res.json() == {"id": "en-1", "status": "pending"}
    api.firestore.update_engagement.assert_called_once_with(
        "en-1",
        {
            "status": "pending",
            "error_message": None,
            "progress_pct": 0,
            "stage": "",
            "stage_detail": "",
        },
    )


def test_delete_purges_only_the_reports_own_prefix_and_keeps_the_csv(
    engagement_api: SimpleNamespace,
) -> None:
    from models_insights import EngagementSignalSpec

    api = engagement_api
    signal = EngagementSignalSpec(
        kind="barc", upload_id="up-csv", csv_gcs_uri=_csv_uri(api)
    )
    api.add_engagement("en-1", signal=signal)
    api.add_engagement("en-12", signal=signal)
    res = api.client.delete(f"{BASE}/en-1", headers=api.master)
    assert res.json() == {"status": "deleted"}
    # The trailing slash keeps en-12's objects out of en-1's purge.
    api.storage.delete_prefix.assert_called_once_with("engagement/en-1/")
    api.firestore.delete_engagement.assert_called_once_with("en-1")
    # The CSV is a user file on the Files page; neither it nor its record is touched.
    api.storage.delete_blob.assert_not_called()
    api.firestore.delete_upload_record.assert_not_called()
    api.firestore.delete_scene_analysis.assert_not_called()


def test_delete_of_an_unknown_report_purges_nothing(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    assert api.client.delete(f"{BASE}/en-ghost", headers=api.master).status_code == 404
    api.storage.delete_prefix.assert_not_called()
    api.firestore.delete_engagement.assert_not_called()


@pytest.mark.parametrize(
    ("reports", "detail"),
    [
        (
            ["en-1"],
            "1 engagement report uses this scene analysis. Delete them first.",
        ),
        (
            ["en-1", "en-2"],
            "2 engagement reports use this scene analysis. Delete them first.",
        ),
    ],
)
def test_a_scene_analysis_with_dependent_reports_cannot_be_deleted(
    engagement_api: SimpleNamespace, reports: list[str], detail: str
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    for record_id in reports:
        # Archived reports still open their workspace, so they count too.
        api.add_engagement(record_id, archived=True)
    api.add_engagement("en-other", scene_analysis_id="sa-2")
    res = api.client.delete(f"{SCENES}/sa-1", headers=api.master)
    assert (res.status_code, res.json()) == (409, {"detail": detail})
    api.storage.delete_prefix.assert_not_called()
    api.firestore.delete_scene_analysis.assert_not_called()


def test_a_scene_analysis_is_deletable_once_its_reports_are_gone(
    engagement_api: SimpleNamespace,
) -> None:
    api = engagement_api
    api.add_analysis("sa-1")
    api.add_engagement("en-other", scene_analysis_id="sa-2")
    res = api.client.delete(f"{SCENES}/sa-1", headers=api.master)
    assert res.json() == {"status": "deleted"}
    api.firestore.find_engagements_for_analysis.assert_called_once_with("sa-1")
    api.storage.delete_prefix.assert_called_once_with("scene_analysis/sa-1/")
    api.firestore.delete_scene_analysis.assert_called_once_with("sa-1")


# ── Report ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
def test_report_is_409_until_the_job_completes(
    engagement_api: SimpleNamespace, status: str
) -> None:
    api = engagement_api
    stale = f"gs://{api.bucket}/engagement/en-1/report.json"
    api.add_engagement("en-1", status=status, report_gcs_uri=stale)
    res = api.client.get(f"{BASE}/en-1/report", headers=api.master)
    assert (res.status_code, res.json()) == (
        409,
        {"detail": "Engagement report is not ready"},
    )
    api.storage.download_bytes.assert_not_called()


def _completed(api: SimpleNamespace) -> str:
    uri = f"gs://{api.bucket}/engagement/en-1/report.json"
    api.add_engagement("en-1", status="completed", report_gcs_uri=uri)
    return uri


def test_report_returns_the_stored_document(engagement_api: SimpleNamespace) -> None:
    api = engagement_api
    uri = _completed(api)
    report = {"schema_version": "engagement-report-v1", "extrema": [], "kpis": {}}
    api.blobs[uri] = json.dumps(report).encode()
    res = api.client.get(f"{BASE}/en-1/report", headers=api.guest)
    assert (res.status_code, res.json()) == (200, report)
    api.storage.download_bytes.assert_called_once_with(uri)


@pytest.mark.parametrize("failure", ["storage_error", "not_json", "not_an_object"])
def test_report_read_failure_is_a_generic_502(
    engagement_api: SimpleNamespace, failure: str
) -> None:
    api = engagement_api
    uri = _completed(api)
    if failure == "storage_error":
        api.storage.download_bytes.side_effect = PermissionError(f"denied {SECRET}")
    elif failure == "not_json":
        api.blobs[uri] = f"<html>{SECRET}</html>".encode()
    else:
        api.blobs[uri] = json.dumps([SECRET]).encode()
    res = api.client.get(f"{BASE}/en-1/report", headers=api.master)
    assert (res.status_code, res.json()) == (502, {"detail": "Report is unavailable"})
    assert SECRET not in res.text


# ── Pricing registries ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("feature", "record_id"), [("engagement", "en-1"), ("scene_analysis", "sa-1")]
)
def test_services_used_panel_endpoints_know_both_insight_features(
    engagement_api: SimpleNamespace, feature: str, record_id: str
) -> None:
    from models import UsageMetrics
    from pricing_config import DEFAULT_TEXT_MODEL, cost_for_text

    api = engagement_api
    usage = UsageMetrics(
        input_tokens=40_000, output_tokens=5_000, model_name=DEFAULT_TEXT_MODEL
    )
    api.add_analysis("sa-1", usage=usage)
    api.add_engagement("en-1", usage=usage)
    catalog = api.client.get("/api/v1/pricing/features", headers=api.master).json()
    services = catalog["features"][feature]["services"]
    assert [s["id"] for s in services] == ["gemini_text"]
    res = api.client.get(
        f"/api/v1/pricing/usage/{feature}/{record_id}", headers=api.master
    )
    assert res.status_code == 200
    (item,) = res.json()["services"]
    assert (item["id"], item["units"]) == ("gemini_text", 45_000)
    expected = cost_for_text(DEFAULT_TEXT_MODEL, 40_000, 5_000)
    assert expected > 0 and res.json()["total_usd"] == pytest.approx(expected)

"""Engagement router: relate a video's timeline to an engagement signal.

The API only queues work. `POST` writes a `pending` record that the worker's
`EngagementProcessor` picks up once the linked scene analysis is completed;
the finished `report.json` is served from GCS by `GET /{id}/report`.

An engagement record never re-analyses a video: it links to an existing scene
analysis, reuses a live one for the same source, or queues a new one. The
signal is a built-in template (simulated data) or an uploaded BARC CSV, which
the client names by upload id only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

import deps
from helpers import (
    ensure_services_ready,
    get_or_404,
    list_completed_production_sources,
    list_video_upload_sources,
    sign_record_urls,
    sign_records_concurrently,
)
from insight_records import build_scene_analysis_record, requeue_updates
from models import EngagementRecord, EngagementSignalSpec, SceneAnalysisRecord
from routers._crud import register_crud_routes
from signal_files import (
    SignalFile,
    SignalFileError,
    read_signal_csv,
    resolve_signal_upload,
)
from signal_parser import preview_signal_csv
from signal_templates import TEMPLATE_IDS, list_templates
from source_resolver import resolve_video_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/engagement", tags=["engagement"])

RESOURCE_LABEL = "Engagement report"
ANALYSIS_LABEL = "Scene analysis"
GCS_PREFIX = "engagement"
MAX_OFFSET_SEC = 86_400.0
_ID_PATTERN = r"^[A-Za-z0-9_\-]+$"
_MODEL_PATTERN = r"^[A-Za-z0-9._\-]+$"
_ANALYSIS_SOURCE_FIELDS = (
    "id",
    "display_name",
    "video_filename",
    "source_type",
    "source_id",
    "status",
    "duration_sec",
    "createdAt",
)


class SignalSpecIn(BaseModel):
    """Where the curve comes from. A CSV is named by upload id, never by URI.

    `csv_filename` is part of the client's signal type, so it is accepted, but
    the stored name always comes from the upload record.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["template", "barc"]
    template_id: Optional[str] = Field(default=None, max_length=64, pattern=_ID_PATTERN)
    upload_id: Optional[str] = Field(default=None, max_length=128, pattern=_ID_PATTERN)
    csv_filename: Optional[str] = Field(default=None, max_length=300)
    time_column: Optional[str] = Field(default=None, max_length=200)
    metric: Optional[str] = Field(default=None, max_length=200)
    offset_sec: float = 0.0


class EngagementCreate(BaseModel):
    """Create payload: one video reference plus the signal to relate it to."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    scene_analysis_id: Optional[str] = Field(
        default=None, max_length=128, pattern=_ID_PATTERN
    )
    source_type: Optional[Literal["upload", "production"]] = None
    source_id: Optional[str] = Field(default=None, max_length=128, pattern=_ID_PATTERN)
    signal: SignalSpecIn
    display_name: str = Field(default="", max_length=200)
    model_id: Optional[str] = Field(
        default=None, max_length=100, pattern=_MODEL_PATTERN
    )
    region: Optional[str] = Field(default=None, max_length=64, pattern=_MODEL_PATTERN)


class SignalPreviewRequest(BaseModel):
    """The uploaded CSV to describe."""

    model_config = ConfigDict(extra="forbid")

    upload_id: str = Field(min_length=1, max_length=128, pattern=_ID_PATTERN)


def _log_ctx(where: str, what: str, why: str, how: str) -> dict[str, str]:
    return {
        "who": "engagement_router",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


# ── Sources, templates, signal preview (literal routes, before `/{record_id}`) ──


@router.get("/templates")
async def list_engagement_templates() -> list[dict[str, Any]]:
    """List the built-in (simulated) engagement curves."""
    return list_templates()


def _signal_preview(signal_file: SignalFile) -> dict[str, Any]:
    """`SignalPreview` of an uploaded CSV, with errors mapped to safe responses."""
    try:
        content = read_signal_csv(signal_file.gcs_uri)
    except SignalFileError as exc:
        raise _bad_request(str(exc))
    except Exception as exc:
        logger.error(
            f"Signal file {signal_file.upload_id} could not be read: {exc}",
            extra=_log_ctx(
                "_signal_preview",
                f"download_failed:{signal_file.upload_id}",
                str(exc),
                "download_bytes",
            ),
        )
        raise HTTPException(status_code=502, detail="Signal file is unavailable")
    try:
        return preview_signal_csv(content, signal_file.filename)
    except ValueError as exc:
        # The parser's `ValueError` messages are written for the user.
        raise _bad_request(str(exc))
    except Exception as exc:
        logger.error(
            f"Signal file {signal_file.upload_id} could not be parsed: {exc}",
            extra=_log_ctx(
                "_signal_preview",
                f"parse_failed:{signal_file.upload_id}",
                str(exc),
                "preview_signal_csv",
            ),
        )
        raise HTTPException(status_code=500, detail="Signal preview failed")


@router.post("/signal-preview")
async def preview_engagement_signal(body: SignalPreviewRequest) -> dict[str, Any]:
    """Describe an uploaded BARC CSV: columns, detected roles, sample rows."""
    ensure_services_ready()
    signal_file = resolve_signal_upload(body.upload_id)
    return await asyncio.to_thread(_signal_preview, signal_file)


@router.get("/sources/uploads")
async def list_engagement_upload_sources() -> list[dict[str, Any]]:
    """List uploaded video files that can be analysed."""
    return list_video_upload_sources()


@router.get("/sources/productions")
async def list_engagement_production_sources() -> list[dict[str, Any]]:
    """List completed studio productions that can be analysed."""
    return list_completed_production_sources(
        extra_fields={"orientation": "orientation"}
    )


def _analysis_source(record: SceneAnalysisRecord) -> dict[str, Any]:
    """Picker entry for one scene analysis, with a signed URL for its video."""
    entry = {name: getattr(record, name) for name in _ANALYSIS_SOURCE_FIELDS}
    uri = record.video_gcs_uri
    signed = bool(deps.storage_svc and uri)
    entry["video_signed_url"] = deps.storage_svc.get_signed_url(uri) if signed else ""
    return entry


@router.get("/sources/analyses")
async def list_engagement_analysis_sources() -> list[dict[str, Any]]:
    """List non-archived scene analyses, newest first, that a report can reuse."""
    ensure_services_ready()
    records = deps.firestore_svc.get_scene_analyses(include_archived=False)
    records = sorted(records, key=lambda r: r.createdAt, reverse=True)
    return await sign_records_concurrently(records, _analysis_source)


# ── CRUD ─────────────────────────────────────────────────────────────


def _sign(record: EngagementRecord) -> dict[str, Any]:
    """Record dict with a signed URL for the source video."""
    return sign_record_urls(
        record,
        {"video_gcs_uri": "video_signed_url"},
        lambda cache: deps.firestore_svc.update_engagement(
            record.id, {"signed_urls": cache}
        ),
    )


def _delete_with_assets(record_id: str) -> None:
    """Delete the record and only the GCS objects under its own prefix.

    The BARC CSV is a user file listed on the Files page and lives outside
    that prefix; it is never deleted here.
    """
    if deps.storage_svc:
        deleted = deps.storage_svc.delete_prefix(f"{GCS_PREFIX}/{record_id}/")
        logger.info(
            f"Purged {deleted} object(s) for engagement report {record_id}",
            extra=_log_ctx(
                "_delete_with_assets", f"purged={deleted}", "record_deleted", record_id
            ),
        )
    deps.firestore_svc.delete_engagement(record_id)


register_crud_routes(
    router,
    resource_label=RESOURCE_LABEL,
    getter=lambda rid: deps.firestore_svc.get_engagement(rid),
    updater=lambda rid, u: deps.firestore_svc.update_engagement(rid, u),
    deleter=_delete_with_assets,
    lister=lambda include_archived=False: deps.firestore_svc.get_engagements(
        include_archived=include_archived
    ),
    sign_one=_sign,
    include_retry=True,
    retry_updates_fn=requeue_updates,
)


# ── Create ───────────────────────────────────────────────────────────


def _check_references(body: EngagementCreate) -> None:
    """Exactly one video reference: an analysis id, or a source type + id."""
    by_source = bool(body.source_type and body.source_id)
    partial_source = bool(body.source_type or body.source_id) and not by_source
    if partial_source or bool(body.scene_analysis_id) == by_source:
        raise _bad_request(
            "Provide either scene_analysis_id, or source_type with source_id"
        )


def _check_signal(spec: SignalSpecIn) -> None:
    """Rules that depend on the signal kind; no datastore access."""
    if spec.kind == "template" and spec.template_id not in TEMPLATE_IDS:
        raise _bad_request("Unknown engagement template")
    if spec.kind == "barc" and not spec.upload_id:
        raise _bad_request("A BARC signal needs upload_id")
    if not math.isfinite(spec.offset_sec) or abs(spec.offset_sec) > MAX_OFFSET_SEC:
        raise _bad_request(
            f"offset_sec must be within {MAX_OFFSET_SEC:.0f} seconds of zero"
        )


def _stored_signal(spec: SignalSpecIn) -> EngagementSignalSpec:
    """The signal as stored: only the fields its kind uses, CSV resolved by id."""
    if spec.kind == "template":
        return EngagementSignalSpec(kind="template", template_id=spec.template_id)
    signal_file = resolve_signal_upload(spec.upload_id or "")
    return EngagementSignalSpec(
        kind="barc",
        upload_id=signal_file.upload_id,
        csv_gcs_uri=signal_file.gcs_uri,
        csv_filename=signal_file.filename,
        time_column=(spec.time_column or "").strip() or None,
        metric=(spec.metric or "").strip() or None,
        offset_sec=spec.offset_sec,
    )


def _existing_analysis(record_id: str) -> SceneAnalysisRecord:
    """A scene analysis the client chose; it must still be able to complete."""
    analysis = get_or_404(
        deps.firestore_svc.get_scene_analysis, record_id, ANALYSIS_LABEL
    )
    if analysis.archived:
        raise _bad_request("Scene analysis is archived")
    if analysis.status == "failed":
        raise _bad_request("Scene analysis failed; retry it or choose another video")
    return analysis


def _analysis_for(
    body: EngagementCreate, invite_code: Optional[str]
) -> SceneAnalysisRecord:
    """The analysis to build on: the chosen one, a live one, or a new one."""
    if body.scene_analysis_id:
        return _existing_analysis(body.scene_analysis_id)
    source = resolve_video_source(body.source_type or "", body.source_id or "")
    reusable = deps.firestore_svc.find_reusable_scene_analysis(
        source.source_type, source.source_id
    )
    if reusable:
        return reusable
    analysis = build_scene_analysis_record(
        source, model_id=body.model_id, region=body.region, invite_code=invite_code
    )
    deps.firestore_svc.create_scene_analysis(analysis)
    logger.info(
        f"Scene analysis {analysis.id} queued for an engagement report",
        extra=_log_ctx(
            "_analysis_for",
            f"queued:{analysis.id}",
            f"{source.source_type}:{source.source_id}",
            "no_reusable_analysis",
        ),
    )
    return analysis


@router.post("")
async def create_engagement(body: EngagementCreate, request: Request) -> dict[str, str]:
    """Queue an engagement report for a video and a signal."""
    ensure_services_ready()
    _check_references(body)
    _check_signal(body.signal)
    invite_code = getattr(request.state, "invite_code", None)
    # The signal is resolved first: a bad CSV must not leave a new analysis behind.
    signal = _stored_signal(body.signal)
    analysis = _analysis_for(body, invite_code)
    record = EngagementRecord(
        scene_analysis_id=analysis.id,
        source_type=analysis.source_type,
        source_id=analysis.source_id,
        video_gcs_uri=analysis.video_gcs_uri,
        video_filename=analysis.video_filename,
        display_name=body.display_name.strip(),
        mime_type=analysis.mime_type,
        signal=signal,
        model_id=body.model_id,
        region=body.region,
        status="pending",
        invite_code=invite_code,
    )
    deps.firestore_svc.create_engagement(record)
    logger.info(
        f"Engagement report {record.id} queued",
        extra=_log_ctx(
            "create_engagement",
            f"queued:{record.id}",
            f"analysis:{analysis.id} signal:{signal.kind}",
            "create_engagement",
        ),
    )
    return {
        "id": record.id,
        "status": record.status,
        "scene_analysis_id": analysis.id,
    }


# ── Report ───────────────────────────────────────────────────────────


def _load_report(record: EngagementRecord) -> dict[str, Any]:
    """Read and parse the record's `report.json` from GCS."""
    report = json.loads(deps.storage_svc.download_bytes(record.report_gcs_uri))
    if not isinstance(report, dict):
        raise ValueError("report.json is not a JSON object")
    return report


@router.get("/{record_id}/report")
async def get_engagement_report(record_id: str) -> dict[str, Any]:
    """Return the report document of a completed engagement job."""
    ensure_services_ready()
    record = get_or_404(deps.firestore_svc.get_engagement, record_id, RESOURCE_LABEL)
    if record.status != "completed" or not record.report_gcs_uri:
        raise HTTPException(status_code=409, detail="Engagement report is not ready")
    if not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    try:
        return await asyncio.to_thread(_load_report, record)
    except Exception as exc:
        logger.error(
            f"Report for engagement {record.id} could not be read: {exc}",
            extra=_log_ctx(
                "get_engagement_report",
                f"report_read_failed:{record.id}",
                str(exc),
                "download_bytes",
            ),
        )
        raise HTTPException(status_code=502, detail="Report is unavailable")

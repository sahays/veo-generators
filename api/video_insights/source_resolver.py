"""Resolve a client-supplied source reference to a video the server trusts.

Clients name a source by `source_type` + `source_id` only. The `gs://` URI is
always read from the stored record, never accepted from the request, so a
caller cannot point an analysis at an arbitrary object.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, NoReturn

from fastapi import HTTPException

import deps

logger = logging.getLogger(__name__)

SOURCE_UPLOAD = "upload"
SOURCE_PRODUCTION = "production"
_DEFAULT_MIME = "video/mp4"


@dataclass(frozen=True)
class ResolvedSource:
    """A video source the server looked up itself."""

    source_type: str
    source_id: str
    gcs_uri: str
    filename: str
    mime_type: str


def _reject(
    status_code: int, detail: str, source_type: str, source_id: str
) -> NoReturn:
    """Log why a source was refused and raise a generic `HTTPException`."""
    logger.warning(
        f"Video source rejected: {detail}",
        extra={
            "who": "source_resolver",
            "where": "resolve_video_source",
            "what": f"{str(source_type)[:32]!r}:{str(source_id)[:64]!r}",
            "why": detail,
            "how": f"http_{status_code}",
        },
    )
    raise HTTPException(status_code=status_code, detail=detail)


def _resolve_upload(source_id: str) -> ResolvedSource:
    upload = deps.firestore_svc.get_upload_record(source_id)
    if not upload:
        _reject(404, "Source not found", SOURCE_UPLOAD, source_id)
    if upload.file_type != "video" or upload.status != "completed":
        _reject(400, "Source is not a completed video upload", SOURCE_UPLOAD, source_id)
    if not str(upload.gcs_uri or "").startswith("gs://"):
        _reject(400, "Source video is not available", SOURCE_UPLOAD, source_id)
    mime = upload.mime_type if str(upload.mime_type).startswith("video/") else None
    return ResolvedSource(
        source_type=SOURCE_UPLOAD,
        source_id=upload.id,
        gcs_uri=upload.gcs_uri,
        filename=upload.display_name or upload.filename,
        mime_type=mime or _DEFAULT_MIME,
    )


def _production_gcs_uri(url: str) -> str:
    """The `gs://` form of a production's final video URL, or `""`.

    Productions may hold an https (signed) URL; it is mapped back to its
    bucket object the same way URL signing recovers stale links.
    """
    if url.startswith("gs://"):
        return url
    if not deps.storage_svc:
        return ""
    recovered = deps.storage_svc.recover_gcs_uri(url)
    return recovered if recovered and recovered.startswith("gs://") else ""


def _resolve_production(source_id: str) -> ResolvedSource:
    production = deps.firestore_svc.get_production(source_id)
    if not production:
        _reject(404, "Source not found", SOURCE_PRODUCTION, source_id)
    status = getattr(production.status, "value", production.status)
    if status != "completed" or not production.final_video_url:
        _reject(
            400, "Production has no completed final video", SOURCE_PRODUCTION, source_id
        )
    gcs_uri = _production_gcs_uri(production.final_video_url)
    if not gcs_uri:
        _reject(400, "Source video is not available", SOURCE_PRODUCTION, source_id)
    return ResolvedSource(
        source_type=SOURCE_PRODUCTION,
        source_id=production.id,
        gcs_uri=gcs_uri,
        filename=f"{production.name}.mp4",
        mime_type=_DEFAULT_MIME,
    )


_RESOLVERS: dict[str, Callable[[str], ResolvedSource]] = {
    SOURCE_UPLOAD: _resolve_upload,
    SOURCE_PRODUCTION: _resolve_production,
}


def resolve_video_source(source_type: str, source_id: str) -> ResolvedSource:
    """Look up a video source by id and return its trusted location.

    Raises `HTTPException`: 503 if persistence is not initialised, 400 for an
    unknown `source_type` or a source that is not a finished video (uploads
    must be completed video files; productions must be completed with a final
    video), 404 when no such record exists.
    """
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    resolver = _RESOLVERS.get(source_type)
    if resolver is None or not source_id:
        _reject(400, "Unknown source", source_type, source_id)
    return resolver(source_id)

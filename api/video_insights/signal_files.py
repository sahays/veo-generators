"""Locate and read the BARC CSV behind an engagement signal.

The client names the file by upload id only. Its `gs://` location is read from
the stored `UploadRecord`, and the size limit is enforced on what is actually
in the bucket, not on the size the browser declared when it uploaded.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import NoReturn

from fastapi import HTTPException

import deps

logger = logging.getLogger(__name__)

MAX_SIGNAL_CSV_BYTES = 10 * 1024 * 1024
_CSV_EXTENSIONS = frozenset({".csv", ".tsv", ".txt"})
_CSV_MIME_TYPES = frozenset(
    {
        "text/csv",
        "text/plain",
        "text/x-csv",
        "text/tab-separated-values",
        "application/csv",
    }
)
_MEDIA_FILE_TYPES = frozenset({"video", "image"})
_TOO_LARGE = "The CSV file is larger than the 10 MB limit."


class SignalFileError(ValueError):
    """A signal file problem whose message is safe to show to the user."""


@dataclass(frozen=True)
class SignalFile:
    """An uploaded CSV the server looked up itself."""

    upload_id: str
    gcs_uri: str
    filename: str


def _reject(status_code: int, detail: str, upload_id: str) -> NoReturn:
    """Log why an upload was refused as a signal file and raise `HTTPException`."""
    logger.warning(
        f"Signal file rejected: {detail}",
        extra={
            "who": "signal_files",
            "where": "resolve_signal_upload",
            "what": f"upload:{str(upload_id)[:64]!r}",
            "why": detail,
            "how": f"http_{status_code}",
        },
    )
    raise HTTPException(status_code=status_code, detail=detail)


def looks_like_csv(filename: str, mime_type: str) -> bool:
    """True when the name or MIME type says the file is delimited text.

    Spreadsheet MIME types are not accepted on their own: browsers report
    `application/vnd.ms-excel` for both `.csv` and binary `.xls` files, so
    those are judged by their extension.
    """
    extension = os.path.splitext(filename or "")[1].lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    return extension in _CSV_EXTENSIONS or mime in _CSV_MIME_TYPES


def stored_size(gcs_uri: str, declared: int = 0) -> int:
    """Size of the object in bytes: the larger of the stored and declared sizes."""
    return max(int(declared or 0), int(deps.storage_svc.get_file_size(gcs_uri) or 0))


def resolve_signal_upload(upload_id: str) -> SignalFile:
    """Look up an uploaded CSV by id and return its trusted location.

    Raises `HTTPException`: 503 if a service is not initialised, 404 when no
    such upload exists, 400 when it is not a completed CSV/text upload or is
    larger than `MAX_SIGNAL_CSV_BYTES`.
    """
    if not deps.firestore_svc or not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    upload = deps.firestore_svc.get_upload_record(upload_id)
    if not upload:
        _reject(404, "Signal file not found", upload_id)
    if upload.status != "completed":
        _reject(400, "Signal file upload is not complete", upload_id)
    filename = upload.display_name or upload.filename
    is_media = upload.file_type in _MEDIA_FILE_TYPES
    if is_media or not looks_like_csv(upload.filename, upload.mime_type):
        _reject(400, "Signal file must be a CSV file", upload_id)
    if not str(upload.gcs_uri or "").startswith("gs://"):
        _reject(400, "Signal file is not available", upload_id)
    if stored_size(upload.gcs_uri, upload.file_size_bytes) > MAX_SIGNAL_CSV_BYTES:
        _reject(400, _TOO_LARGE, upload_id)
    return SignalFile(upload_id=upload.id, gcs_uri=upload.gcs_uri, filename=filename)


def read_signal_csv(gcs_uri: str) -> bytes:
    """Download a signal CSV, refusing anything over `MAX_SIGNAL_CSV_BYTES`.

    The size is checked before the download (object metadata) and again on the
    bytes received. Raises `SignalFileError` when the file is too large;
    storage errors propagate unchanged for the caller to report generically.
    """
    if stored_size(gcs_uri) > MAX_SIGNAL_CSV_BYTES:
        raise SignalFileError(_TOO_LARGE)
    content = deps.storage_svc.download_bytes(gcs_uri)
    if len(content) > MAX_SIGNAL_CSV_BYTES:
        raise SignalFileError(_TOO_LARGE)
    return content

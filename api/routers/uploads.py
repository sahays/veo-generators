import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile

import deps
from helpers import get_or_404, require_firestore, sign_record_urls
from models import (
    CompressedVariant,
    UploadCompleteRequest,
    UploadInitRequest,
    UploadRecord,
)
from routers._crud import register_crud_routes

logger = logging.getLogger(__name__)


def _backfill_file_size(record: UploadRecord) -> None:
    """If the record landed without a known file size (older compressed
    children, mostly), look it up once and persist back so list views show
    a real number instead of zero."""
    if record.file_size_bytes or not record.gcs_uri or not deps.storage_svc:
        return
    size = deps.storage_svc.get_file_size(record.gcs_uri)
    if size <= 0:
        return
    record.file_size_bytes = size
    if deps.firestore_svc:
        deps.firestore_svc.update_upload_record(record.id, {"file_size_bytes": size})


def _sign_upload_urls(record: UploadRecord) -> dict:
    """Sign the main GCS URI plus succeeded compressed variants."""
    _backfill_file_size(record)
    data = sign_record_urls(
        record,
        {"gcs_uri": "signed_url"},
        lambda cache: deps.firestore_svc.update_upload_record(
            record.id, {"signed_urls": cache}
        ),
    )
    if deps.storage_svc:
        variant_cache: dict = {}
        for variant in data.get("compressed_variants", []):
            uri = variant.get("gcs_uri")
            if uri and variant.get("status") == "succeeded":
                url, _ = deps.storage_svc.resolve_cached_url(uri, variant_cache)
                variant["signed_url"] = url
    return data


def _file_type_for(mime: str) -> str:
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    return "other"


router = APIRouter(prefix="/api/v1", tags=["uploads"])

# Standard CRUD lives at /api/v1/uploads/* — register it on a child router so
# the upload + compress endpoints below (which sit at /api/v1/assets/* and
# /api/v1/uploads/{id}/compress*) can keep their existing paths.
_uploads_router = APIRouter(prefix="/uploads")

register_crud_routes(
    _uploads_router,
    resource_label="Upload",
    getter=lambda rid: deps.firestore_svc.get_upload_record(rid),
    updater=lambda rid, u: deps.firestore_svc.update_upload_record(rid, u),
    deleter=lambda rid: deps.firestore_svc.delete_upload_record(rid),
    sign_one=_sign_upload_urls,
    include_list=False,  # custom list below — supports file_type filter
)


@_uploads_router.get("")
async def list_uploads(archived: bool = False, file_type: Optional[str] = None):
    require_firestore()
    records = deps.firestore_svc.get_upload_records(
        include_archived=archived, file_type=file_type
    )
    return [_sign_upload_urls(r) for r in records]


@router.post("/assets/upload/init")
async def upload_init(request: UploadInitRequest):
    """Generate a signed PUT URL for direct-to-GCS upload."""
    if not deps.storage_svc or not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")

    destination = f"uploads/{uuid.uuid4()}-{request.filename}"
    signed = deps.storage_svc.generate_upload_signed_url(
        destination, request.content_type
    )
    record = UploadRecord(
        filename=request.filename,
        mime_type=request.content_type,
        file_type=_file_type_for(request.content_type or ""),
        gcs_uri=signed["gcs_uri"],
        file_size_bytes=request.file_size_bytes,
        status="pending",
    )
    deps.firestore_svc.create_upload_record(record)
    return {
        "record_id": record.id,
        "upload_url": signed["upload_url"],
        "gcs_uri": signed["gcs_uri"],
        "content_type": request.content_type,
        "expires_at": signed["expires_at"],
    }


@router.post("/assets/upload/complete")
async def upload_complete(request: UploadCompleteRequest):
    """Verify a direct upload landed in GCS and finalize the record."""
    if not deps.storage_svc or not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")

    record = get_or_404(
        deps.firestore_svc.get_upload_record, request.record_id, "Upload"
    )
    if not deps.storage_svc.blob_exists(record.gcs_uri):
        deps.firestore_svc.update_upload_record(request.record_id, {"status": "failed"})
        raise HTTPException(status_code=400, detail="File not found in GCS")

    actual_size = deps.storage_svc.get_file_size(record.gcs_uri)
    deps.firestore_svc.update_upload_record(
        request.record_id,
        {"status": "completed", "file_size_bytes": actual_size},
    )
    return {
        "id": record.id,
        "gcs_uri": record.gcs_uri,
        "signed_url": deps.storage_svc.get_signed_url(record.gcs_uri),
        "file_type": record.file_type,
    }


@router.post("/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    if not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = deps.storage_svc.upload_file(content, destination, file.content_type)
    record = UploadRecord(
        filename=file.filename or "unknown",
        mime_type=file.content_type or "",
        file_type=_file_type_for(file.content_type or ""),
        gcs_uri=gcs_uri,
        file_size_bytes=len(content),
    )
    if deps.firestore_svc:
        deps.firestore_svc.create_upload_record(record)
    return {
        "id": record.id,
        "gcs_uri": gcs_uri,
        "signed_url": deps.storage_svc.get_signed_url(gcs_uri),
        "file_type": record.file_type,
    }


def _ensure_compress_services() -> None:
    if not deps.firestore_svc or not deps.transcoder_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")


def _start_compression(
    record: UploadRecord, resolution: str
) -> CompressedVariant:
    job_name, output_uri = deps.transcoder_svc.compress_video(
        record.id, record.gcs_uri, resolution
    )
    variant = CompressedVariant(
        resolution=resolution,
        gcs_uri=output_uri,
        job_name=job_name,
        status="processing",
    )
    # Drop any previously-failed variant at the same resolution before appending.
    updated = [
        v.dict() for v in record.compressed_variants if v.resolution != resolution
    ]
    updated.append(variant.dict())
    deps.firestore_svc.update_upload_record(
        record.id, {"compressed_variants": updated}
    )
    return variant


@_uploads_router.post("/{record_id}/compress")
async def compress_upload(record_id: str, request: dict):
    _ensure_compress_services()
    record = get_or_404(deps.firestore_svc.get_upload_record, record_id, "Upload")
    if record.file_type != "video":
        raise HTTPException(400, "Only video files can be compressed")

    resolution = request.get("resolution")
    if resolution not in ("480p", "720p"):
        raise HTTPException(400, "Resolution must be '480p' or '720p'")

    for v in record.compressed_variants:
        if v.resolution == resolution and v.status in ("processing", "succeeded"):
            raise HTTPException(400, f"{resolution} variant already {v.status}")

    try:
        variant = _start_compression(record, resolution)
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        raise HTTPException(500, str(e))
    return {
        "status": "processing",
        "job_name": variant.job_name,
        "resolution": resolution,
    }


def _materialize_succeeded_variant(
    record: UploadRecord, variant: dict
) -> None:
    """Create the child UploadRecord that points at the compressed file
    so it shows up in upload pickers as a separate selectable resolution."""
    if variant.get("child_upload_id"):
        return
    base, ext = os.path.splitext(record.filename)
    child = UploadRecord(
        filename=f"{base}-{variant['resolution']}{ext}",
        mime_type=record.mime_type,
        file_type="video",
        gcs_uri=variant["gcs_uri"],
        file_size_bytes=(
            deps.storage_svc.get_file_size(variant["gcs_uri"])
            if deps.storage_svc
            else 0
        ),
        parent_upload_id=record.id,
        resolution_label=variant["resolution"],
    )
    deps.firestore_svc.create_upload_record(child)
    variant["child_upload_id"] = child.id


def _refresh_variant_status(record: UploadRecord, variant: dict) -> bool:
    """Poll one transcoder job and mutate variant in place. Returns True if
    the status changed (so the caller can persist the new state)."""
    if variant["status"] != "processing" or not variant["job_name"]:
        return False
    job_state = deps.transcoder_svc.get_job_status(variant["job_name"])
    if job_state == "SUCCEEDED":
        variant["status"] = "succeeded"
        _materialize_succeeded_variant(record, variant)
        return True
    if job_state in ("FAILED", "UNKNOWN"):
        variant["status"] = "failed"
        return True
    return False


@_uploads_router.get("/{record_id}/compress-status")
async def get_compress_status(record_id: str):
    _ensure_compress_services()
    record = get_or_404(deps.firestore_svc.get_upload_record, record_id, "Upload")

    variants = [v.dict() for v in record.compressed_variants]
    dirty = any(_refresh_variant_status(record, v) for v in variants)
    if dirty:
        deps.firestore_svc.update_upload_record(
            record_id, {"compressed_variants": variants}
        )

    if deps.storage_svc:
        for v in variants:
            if v["status"] == "succeeded" and v["gcs_uri"]:
                v["signed_url"] = deps.storage_svc.get_signed_url(v["gcs_uri"])
    return {"variants": variants}


router.include_router(_uploads_router)

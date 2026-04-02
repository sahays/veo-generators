import os
import uuid
import logging

from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Optional

import deps
from models import (
    UploadRecord,
    CompressedVariant,
    UploadInitRequest,
    UploadCompleteRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["uploads"])


def _sign_upload_urls(record: UploadRecord) -> dict:
    """Return record dict with signed URLs for the file and compressed variants."""
    data = record.dict()
    if not deps.storage_svc:
        return data

    # Backfill file size if missing (e.g. compressed children created before fix)
    if record.file_size_bytes == 0 and record.gcs_uri:
        size = deps.storage_svc.get_file_size(record.gcs_uri)
        if size > 0:
            data["file_size_bytes"] = size
            if deps.firestore_svc:
                deps.firestore_svc.update_upload_record(
                    record.id, {"file_size_bytes": size}
                )

    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri or not gcs_uri.startswith("gs://"):
            return gcs_uri
        url, changed = deps.storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    # Sign main file
    data["signed_url"] = _resolve(record.gcs_uri)

    # Sign compressed variants
    for variant in data.get("compressed_variants", []):
        if variant.get("gcs_uri") and variant.get("status") == "succeeded":
            variant["signed_url"] = _resolve(variant["gcs_uri"])

    if dirty and deps.firestore_svc:
        deps.firestore_svc.update_upload_record(record.id, {"signed_urls": cache})

    data.pop("signed_urls", None)
    return data


@router.post("/assets/upload/init")
async def upload_init(request: UploadInitRequest):
    """Generate a signed PUT URL for direct-to-GCS upload."""
    if not deps.storage_svc or not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")

    mime = request.content_type or ""
    if mime.startswith("video/"):
        file_type = "video"
    elif mime.startswith("image/"):
        file_type = "image"
    else:
        file_type = "other"

    destination = f"uploads/{uuid.uuid4()}-{request.filename}"
    signed = deps.storage_svc.generate_upload_signed_url(
        destination, request.content_type
    )

    record = UploadRecord(
        filename=request.filename,
        mime_type=request.content_type,
        file_type=file_type,
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

    record = deps.firestore_svc.get_upload_record(request.record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload record not found")

    if not deps.storage_svc.blob_exists(record.gcs_uri):
        deps.firestore_svc.update_upload_record(request.record_id, {"status": "failed"})
        raise HTTPException(status_code=400, detail="File not found in GCS")

    actual_size = deps.storage_svc.get_file_size(record.gcs_uri)
    deps.firestore_svc.update_upload_record(
        request.record_id,
        {"status": "completed", "file_size_bytes": actual_size},
    )

    signed_url = deps.storage_svc.get_signed_url(record.gcs_uri)
    return {
        "id": record.id,
        "gcs_uri": record.gcs_uri,
        "signed_url": signed_url,
        "file_type": record.file_type,
    }


@router.post("/assets/upload")
async def upload_asset(file: UploadFile = File(...)):
    if not deps.storage_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    content = await file.read()
    destination = f"uploads/{uuid.uuid4()}-{file.filename}"
    gcs_uri = deps.storage_svc.upload_file(content, destination, file.content_type)
    signed_url = deps.storage_svc.get_signed_url(gcs_uri)

    # Derive file_type from MIME prefix
    mime = file.content_type or ""
    if mime.startswith("video/"):
        file_type = "video"
    elif mime.startswith("image/"):
        file_type = "image"
    else:
        file_type = "other"

    # Persist to Firestore
    record = UploadRecord(
        filename=file.filename or "unknown",
        mime_type=mime,
        file_type=file_type,
        gcs_uri=gcs_uri,
        file_size_bytes=len(content),
    )
    if deps.firestore_svc:
        deps.firestore_svc.create_upload_record(record)

    return {
        "id": record.id,
        "gcs_uri": gcs_uri,
        "signed_url": signed_url,
        "file_type": file_type,
    }


@router.get("/uploads")
async def list_uploads(archived: bool = False, file_type: Optional[str] = None):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    records = deps.firestore_svc.get_upload_records(
        include_archived=archived, file_type=file_type
    )
    return [_sign_upload_urls(r) for r in records]


@router.get("/uploads/{record_id}")
async def get_upload(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    return _sign_upload_urls(record)


@router.post("/uploads/{record_id}/compress")
async def compress_upload(record_id: str, request: dict):
    if not deps.firestore_svc or not deps.transcoder_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    if record.file_type != "video":
        raise HTTPException(
            status_code=400, detail="Only video files can be compressed"
        )

    resolution = request.get("resolution")
    if resolution not in ("480p", "720p"):
        raise HTTPException(
            status_code=400, detail="Resolution must be '480p' or '720p'"
        )

    # Check if variant already exists and is processing/succeeded
    for v in record.compressed_variants:
        if v.resolution == resolution and v.status in ("processing", "succeeded"):
            raise HTTPException(
                status_code=400,
                detail=f"{resolution} variant already {v.status}",
            )

    try:
        job_name, output_uri = deps.transcoder_svc.compress_video(
            record_id, record.gcs_uri, resolution
        )
        new_variant = CompressedVariant(
            resolution=resolution,
            gcs_uri=output_uri,
            job_name=job_name,
            status="processing",
        )
        # Remove any failed variant with same resolution, then append new one
        updated_variants = [
            v.dict() for v in record.compressed_variants if v.resolution != resolution
        ]
        updated_variants.append(new_variant.dict())
        deps.firestore_svc.update_upload_record(
            record_id, {"compressed_variants": updated_variants}
        )
        return {"status": "processing", "job_name": job_name, "resolution": resolution}
    except Exception as e:
        logger.error(f"Compression failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/uploads/{record_id}/compress-status")
async def get_compress_status(record_id: str):
    if not deps.firestore_svc or not deps.transcoder_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")

    updated = False
    variants = [v.dict() for v in record.compressed_variants]
    for v in variants:
        if v["status"] == "processing" and v["job_name"]:
            job_state = deps.transcoder_svc.get_job_status(v["job_name"])
            if job_state == "SUCCEEDED":
                v["status"] = "succeeded"
                updated = True
                # Create a child UploadRecord if not already created
                if not v.get("child_upload_id"):
                    resolution = v["resolution"]
                    base, ext = os.path.splitext(record.filename)
                    child_filename = f"{base}-{resolution}{ext}"
                    child_size = (
                        deps.storage_svc.get_file_size(v["gcs_uri"])
                        if deps.storage_svc
                        else 0
                    )
                    child_record = UploadRecord(
                        filename=child_filename,
                        mime_type=record.mime_type,
                        file_type="video",
                        gcs_uri=v["gcs_uri"],
                        file_size_bytes=child_size,
                        parent_upload_id=record_id,
                        resolution_label=resolution,
                    )
                    deps.firestore_svc.create_upload_record(child_record)
                    v["child_upload_id"] = child_record.id
            elif job_state in ("FAILED", "UNKNOWN"):
                v["status"] = "failed"
                updated = True

    if updated:
        deps.firestore_svc.update_upload_record(
            record_id, {"compressed_variants": variants}
        )

    # Sign URLs for succeeded variants
    result_variants = []
    for v in variants:
        if v["status"] == "succeeded" and v["gcs_uri"] and deps.storage_svc:
            v["signed_url"] = deps.storage_svc.get_signed_url(v["gcs_uri"])
        result_variants.append(v)

    return {"variants": result_variants}


@router.patch("/uploads/{record_id}")
async def update_upload(record_id: str, body: dict):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")

    updates = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    deps.firestore_svc.update_upload_record(record_id, updates)
    return {"status": "updated"}


@router.post("/uploads/{record_id}/archive")
async def archive_upload(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    deps.firestore_svc.update_upload_record(record_id, {"archived": True})
    return {"status": "archived"}


@router.delete("/uploads/{record_id}")
async def delete_upload(record_id: str):
    if not deps.firestore_svc:
        raise HTTPException(status_code=503, detail="Service not initialized")
    record = deps.firestore_svc.get_upload_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Upload not found")
    deps.firestore_svc.delete_upload_record(record_id)
    return {"status": "deleted"}

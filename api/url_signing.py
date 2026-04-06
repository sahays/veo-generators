"""URL signing utilities for GCS resources."""

from typing import Callable, Optional

import deps
from models import Project


def sign_record_urls(
    record,
    uri_fields: dict[str, str],
    update_fn: Callable[[dict], None],
) -> dict:
    """Generic URL signing for records with a signed_urls cache.

    Args:
        record: Pydantic model with a signed_urls dict field.
        uri_fields: mapping of record field name to output key
            (e.g. {"source_gcs_uri": "source_signed_url"}).
        update_fn: callable to persist updated cache back to Firestore.

    Returns:
        Record dict with signed URL keys added and signed_urls cache removed.
    """
    data = record.dict()
    if not deps.storage_svc:
        return data

    cache = data.get("signed_urls") or {}
    dirty = False

    for field_name, output_key in uri_fields.items():
        gcs_uri = getattr(record, field_name, None)
        if not gcs_uri:
            continue
        url, changed = deps.storage_svc.resolve_cached_url(gcs_uri, cache)
        data[output_key] = url
        if changed:
            dirty = True

    if dirty and deps.firestore_svc:
        update_fn(cache)

    data.pop("signed_urls", None)
    return data


def sign_production_urls(production: Project, thumbnails_only: bool = False) -> dict:
    """Return a dict with media URLs resolved from cache.

    When thumbnails_only=True, only sign scene thumbnails (for list views).
    Persists updated signed URL cache back to Firestore when any URL was refreshed.
    """
    if not deps.storage_svc:
        return production.dict()

    data = production.dict()
    cache = data.get("signed_urls") or {}
    dirty = False

    def _resolve(gcs_uri: str) -> str:
        nonlocal dirty
        if not gcs_uri:
            return ""
        if not gcs_uri.startswith("gs://"):
            recovered = deps.storage_svc.recover_gcs_uri(gcs_uri)
            if recovered:
                gcs_uri = recovered
            else:
                return gcs_uri
        url, changed = deps.storage_svc.resolve_cached_url(gcs_uri, cache)
        if changed:
            dirty = True
        return url

    for scene in data.get("scenes", []):
        if scene.get("thumbnail_url"):
            scene["thumbnail_url"] = _resolve(scene["thumbnail_url"])
        if not thumbnails_only and scene.get("video_url"):
            scene["video_url"] = _resolve(scene["video_url"])
    if not thumbnails_only:
        if data.get("final_video_url"):
            data["final_video_url"] = _resolve(data["final_video_url"])
        if data.get("reference_image_url"):
            data["reference_image_url"] = _resolve(data["reference_image_url"])

    if dirty and deps.firestore_svc:
        deps.firestore_svc.update_production(production.id, {"signed_urls": cache})

    data.pop("signed_urls", None)
    return data


def _sign_gcs_uri(gcs_uri: str) -> str:
    """Sign a single GCS URI, returning the original if not a gs:// URI."""
    if not deps.storage_svc or not gcs_uri:
        return ""
    if gcs_uri.startswith("gs://"):
        return deps.storage_svc.get_signed_url(gcs_uri)
    return gcs_uri


def list_upload_sources(
    file_type: str, url_key: str, extra_fields: Optional[list[str]] = None
) -> list[dict]:
    """Return signed upload sources for the given file type.

    Args:
        file_type: "video" or "image"
        url_key: output key for signed URL (e.g. "video_signed_url")
        extra_fields: additional UploadRecord fields to include
    """
    from helpers import require_firestore

    require_firestore()
    uploads = deps.firestore_svc.get_upload_records(file_type=file_type)
    results = []
    for u in uploads:
        entry = {
            "id": u.id,
            "filename": u.filename,
            "display_name": u.display_name or "",
            "gcs_uri": u.gcs_uri,
            url_key: _sign_gcs_uri(u.gcs_uri),
            "file_size_bytes": u.file_size_bytes,
            "createdAt": u.createdAt.isoformat() if u.createdAt else None,
        }
        if extra_fields:
            for field in extra_fields:
                entry[field] = getattr(u, field, None)
        results.append(entry)
    return results


def list_video_upload_sources() -> list[dict]:
    """Return signed upload video sources."""
    return list_upload_sources("video", "video_signed_url")


def list_image_upload_sources() -> list[dict]:
    """Return signed upload image sources."""
    return list_upload_sources("image", "image_signed_url", ["mime_type"])


def list_completed_production_sources(
    extra_fields: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Return signed completed production sources.

    Args:
        extra_fields: optional mapping of production attribute name to output key.
    """
    from helpers import require_firestore

    require_firestore()
    productions = deps.firestore_svc.get_productions()
    completed = [
        p for p in productions if p.status.value == "completed" and p.final_video_url
    ]
    results = []
    for p in completed:
        entry = {
            "id": p.id,
            "name": p.name,
            "final_video_url": p.final_video_url,
            "video_signed_url": _sign_gcs_uri(p.final_video_url),
            "createdAt": p.createdAt.isoformat() if p.createdAt else None,
        }
        if extra_fields:
            for attr, key in extra_fields.items():
                entry[key] = getattr(p, attr, None)
        results.append(entry)
    return results

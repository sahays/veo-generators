"""CRUD route factory shared across feature routers.

Every feature router (adapts, reframe, promo, key_moments, thumbnails,
productions) registers a subset of these endpoints. Feature-specific
routes (analyze, create, collage, etc.) stay inline in each router.

All endpoints registered here use `{record_id}` as the path parameter.
URL patterns are identical on the wire; only the Python parameter name
is fixed.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Request

from helpers import ensure_services_ready, get_or_404
from url_signing import sign_records_concurrently


def _default_retry_updates(_record: Any) -> dict[str, Any]:
    """Return default pending retry fields for a failed record."""
    return {"status": "pending", "error_message": None, "progress_pct": 0}


def _register_read_routes(
    router: APIRouter,
    resource_label: str,
    getter: Callable[..., Any],
    lister: Optional[Callable[..., Any]],
    sign_one: Callable[..., Any],
    sign_for_list: Callable[..., Any],
    include_list: bool,
    include_get: bool,
) -> None:
    """Register GET list and GET by ID routes on `router`."""
    if include_list and lister:

        @router.get("")
        async def _list(
            request: Request, archived: bool = False
        ) -> list[dict[str, Any]]:
            _ = request
            ensure_services_ready()
            records = lister(include_archived=archived)
            return await sign_records_concurrently(records, sign_for_list)

    if include_get:

        @router.get("/{record_id}")
        async def _get(record_id: str) -> dict[str, Any]:
            ensure_services_ready()
            record = get_or_404(getter, record_id, resource_label)
            return sign_one(record)


def _register_archive_routes(
    router: APIRouter,
    resource_label: str,
    getter: Callable[..., Any],
    updater: Optional[Callable[..., Any]],
    include_archive: bool,
    include_unarchive: bool,
) -> None:
    """Register POST archive and unarchive routes on `router`."""
    if include_archive and updater:

        @router.post("/{record_id}/archive")
        async def _archive(record_id: str) -> dict[str, str]:
            ensure_services_ready()
            get_or_404(getter, record_id, resource_label)
            updater(record_id, {"archived": True})
            return {"status": "archived"}

    if include_unarchive and updater:

        @router.post("/{record_id}/unarchive")
        async def _unarchive(record_id: str) -> dict[str, str]:
            ensure_services_ready()
            get_or_404(getter, record_id, resource_label)
            updater(record_id, {"archived": False})
            return {"status": "unarchived"}


def _register_mutation_routes(
    router: APIRouter,
    resource_label: str,
    getter: Callable[..., Any],
    updater: Optional[Callable[..., Any]],
    deleter: Optional[Callable[..., Any]],
    include_patch: bool,
    include_delete: bool,
    include_retry: bool,
    retry_updates_fn: Callable[..., dict[str, Any]],
) -> None:
    """Register PATCH, DELETE, and POST retry routes on `router`."""
    if include_patch and updater:

        @router.patch("/{record_id}")
        async def _patch(record_id: str, body: dict[str, Any]) -> dict[str, str]:
            ensure_services_ready()
            get_or_404(getter, record_id, resource_label)
            updates = _extract_patch_updates(body)
            if not updates:
                raise HTTPException(400, "No valid fields to update")
            updater(record_id, updates)
            return {"status": "updated"}

    if include_delete and deleter:

        @router.delete("/{record_id}")
        async def _delete(record_id: str) -> dict[str, str]:
            ensure_services_ready()
            get_or_404(getter, record_id, resource_label)
            deleter(record_id)
            return {"status": "deleted"}

    if include_retry and updater:

        @router.post("/{record_id}/retry")
        async def _retry(record_id: str) -> dict[str, str]:
            ensure_services_ready()
            record = get_or_404(getter, record_id, resource_label)
            if record.status in ("pending", "completed"):
                raise HTTPException(
                    400, f"Cannot retry a {record.status} {resource_label.lower()}"
                )
            updater(record_id, retry_updates_fn(record))
            return {"id": record_id, "status": "pending"}


def register_crud_routes(
    router: APIRouter,
    *,
    resource_label: str,
    getter: Callable[..., Any],
    updater: Optional[Callable[..., Any]] = None,
    deleter: Optional[Callable[..., Any]] = None,
    lister: Optional[Callable[..., Any]] = None,
    sign_one: Callable[..., Any] = lambda r: r.dict(),
    sign_list: Optional[Callable[..., Any]] = None,
    include_list: bool = True,
    include_get: bool = True,
    include_patch: bool = True,
    include_archive: bool = True,
    include_unarchive: bool = False,
    include_delete: bool = True,
    include_retry: bool = False,
    retry_updates_fn: Callable[..., dict[str, Any]] = _default_retry_updates,
) -> None:
    """Register standard CRUD endpoints on `router`."""
    _sign_for_list = sign_list or sign_one
    _register_read_routes(
        router,
        resource_label,
        getter,
        lister,
        sign_one,
        _sign_for_list,
        include_list,
        include_get,
    )
    _register_archive_routes(
        router, resource_label, getter, updater, include_archive, include_unarchive
    )
    _register_mutation_routes(
        router,
        resource_label,
        getter,
        updater,
        deleter,
        include_patch,
        include_delete,
        include_retry,
        retry_updates_fn,
    )


_ALLOWED_PATCH_STRING_FIELDS = (
    "display_name",
    "name",
    "type",
    "base_concept",
    "video_length",
    "orientation",
    "language",
    "reference_image_url",
    "render_quality",
    "video_resolution",
    "status",
)

_ALLOWED_PATCH_OBJECT_FIELDS = (
    "scenes",
    "global_style",
    "continuity",
)


def _extract_patch_updates(body: dict[str, Any]) -> dict[str, Any]:
    """Extract allowed fields for PATCH endpoints across feature routers."""
    updates: dict[str, Any] = {}
    for field in _ALLOWED_PATCH_STRING_FIELDS:
        if field in body and body[field] is not None:
            updates[field] = str(body[field]).strip()
    for field in _ALLOWED_PATCH_OBJECT_FIELDS:
        if field in body and body[field] is not None:
            updates[field] = body[field]
    return updates

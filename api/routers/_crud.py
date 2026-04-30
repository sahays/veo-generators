"""CRUD route factory shared across feature routers.

Every feature router (adapts, reframe, promo, key_moments, thumbnails,
productions) registers a subset of these endpoints. Feature-specific
routes (analyze, create, collage, etc.) stay inline in each router.

All endpoints registered here use `{record_id}` as the path parameter.
URL patterns are identical on the wire; only the Python parameter name
is fixed.
"""

from typing import Callable, Optional

from fastapi import HTTPException, Request

from helpers import get_or_404, require_firestore


def _default_retry_updates(_record) -> dict:
    return {"status": "pending", "error_message": None, "progress_pct": 0}


def register_crud_routes(
    router,
    *,
    resource_label: str,
    getter: Callable,
    updater: Optional[Callable] = None,
    deleter: Optional[Callable] = None,
    lister: Optional[Callable] = None,
    sign_one: Callable = lambda r: r.dict(),
    sign_list: Optional[Callable] = None,  # defaults to sign_one
    include_list: bool = True,
    include_get: bool = True,
    include_patch: bool = True,
    include_archive: bool = True,
    include_unarchive: bool = False,
    include_delete: bool = True,
    include_retry: bool = False,
    retry_updates_fn: Callable = _default_retry_updates,
) -> None:
    """Register standard CRUD endpoints on `router`.

    Only endpoints whose `include_*` flag is True *and* whose backing
    callable is provided get registered. `sign_one(record) -> dict` is
    applied to both list and get responses.
    """

    _sign_for_list = sign_list or sign_one

    if include_list and lister:

        @router.get("")
        async def _list(request: Request, archived: bool = False):
            require_firestore()
            records = lister(include_archived=archived)
            return [_sign_for_list(r) for r in records]

    if include_get:

        @router.get("/{record_id}")
        async def _get(record_id: str):
            require_firestore()
            record = get_or_404(getter, record_id, resource_label)
            return sign_one(record)

    if include_patch and updater:

        @router.patch("/{record_id}")
        async def _patch(record_id: str, body: dict):
            require_firestore()
            get_or_404(getter, record_id, resource_label)
            updates = _extract_patch_updates(body)
            if not updates:
                raise HTTPException(400, "No valid fields to update")
            updater(record_id, updates)
            return {"status": "updated"}

    if include_archive and updater:

        @router.post("/{record_id}/archive")
        async def _archive(record_id: str):
            require_firestore()
            get_or_404(getter, record_id, resource_label)
            updater(record_id, {"archived": True})
            return {"status": "archived"}

    if include_unarchive and updater:

        @router.post("/{record_id}/unarchive")
        async def _unarchive(record_id: str):
            require_firestore()
            get_or_404(getter, record_id, resource_label)
            updater(record_id, {"archived": False})
            return {"status": "unarchived"}

    if include_delete and deleter:

        @router.delete("/{record_id}")
        async def _delete(record_id: str):
            require_firestore()
            get_or_404(getter, record_id, resource_label)
            deleter(record_id)
            return {"status": "deleted"}

    if include_retry and updater:

        @router.post("/{record_id}/retry")
        async def _retry(record_id: str):
            require_firestore()
            record = get_or_404(getter, record_id, resource_label)
            if record.status in ("pending", "completed"):
                raise HTTPException(
                    400,
                    f"Cannot retry a {record.status} {resource_label.lower()}",
                )
            updater(record_id, retry_updates_fn(record))
            return {"id": record_id, "status": "pending"}


def _extract_patch_updates(body: dict) -> dict:
    """The only field currently allowed via PATCH is display_name. Centralized
    so feature routers stay in sync if we add more."""
    updates: dict = {}
    if "display_name" in body:
        updates["display_name"] = str(body["display_name"]).strip()
    return updates

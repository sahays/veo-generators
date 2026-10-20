"""Transactional versioning and Shot reference resolution helpers for `Repo`."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..schema import Appearance, Asset, CastInShot, Shot, Status
from ..store.codec import decode, encode
from .change_requests import close_critic_change_requests

if TYPE_CHECKING:
    from .service import Repo

_VERSION_SUFFIX_RE = re.compile(r"^(?P<base>.+?)_v(?P<ver>\d+)$")


def strip_version_suffix(node_id: str) -> str:
    m = _VERSION_SUFFIX_RE.match(node_id)
    return m.group("base") if m else node_id


def _supersede_active_docs(
    tx: Any,
    collection: str,
    docs: list[dict[str, Any]],
    fallback_supersedes: str | None,
) -> tuple[int, str | None, list[str]]:
    max_ver = max((int(d.get("version", 0)) for d in docs), default=0)
    prev_active = [d for d in docs if d.get("status") != str(Status.SUPERSEDED)]
    supersedes_id = prev_active[-1]["id"] if prev_active else fallback_supersedes
    superseded_ids: list[str] = []
    for prev in prev_active:
        prev_copy = dict(prev)
        prev_copy["status"] = str(Status.SUPERSEDED)
        tx.set(collection, prev["id"], prev_copy)
        superseded_ids.append(prev["id"])
    return max_ver + 1, supersedes_id, superseded_ids


def mint_versioned_appearance(repo: Repo, app: Appearance) -> Appearance:
    """Mint a new versioned Appearance (`v1`, `v2`...) inside a transaction and mark referencing shots stale."""
    base_id = f"app_{app.entity_id}_{app.state_label}"
    with repo.store.transaction() as tx:
        existing_all = repo.store.query(
            "appearances",
            filters=[
                ("entity_id", "==", app.entity_id),
                ("state_label", "==", app.state_label),
            ],
        )
        new_ver, supersedes_id, superseded_ids = _supersede_active_docs(
            tx, "appearances", existing_all, app.supersedes
        )
        minted = app.model_copy(
            update={
                "id": f"{base_id}_v{new_ver}",
                "version": new_ver,
                "supersedes": supersedes_id,
            }
        )
        tx.set("appearances", minted.id, encode(minted))

    for old_id in superseded_ids:
        propagate_staleness(
            repo, old_id, f"Appearance {old_id} superseded by {minted.id}"
        )
    return minted


def _link_minted_asset_to_appearances(
    repo: Repo, minted: Asset, superseded_ids: list[str]
) -> None:
    for app_id in minted.appearance_ids:
        app_node = repo.get_appearance(app_id)
        if app_node and minted.id not in app_node.asset_ids:
            new_asset_ids = [
                aid for aid in app_node.asset_ids if aid not in superseded_ids
            ] + [minted.id]
            repo.update_appearance_status(
                app_node.id, app_node.status, asset_ids=new_asset_ids
            )
        for old_asset_id in superseded_ids:
            propagate_staleness(
                repo, app_id, f"Asset {old_asset_id} superseded by {minted.id}"
            )


def mint_versioned_asset(repo: Repo, asset: Asset) -> Asset:
    """Mint a new versioned Asset (`_v1`, `_v2`...) and propagate staleness if superseding."""
    base_id = strip_version_suffix(asset.id)
    with repo.store.transaction() as tx:
        matching = [
            d
            for d in repo.store.query("assets")
            if strip_version_suffix(str(d.get("id", ""))) == base_id
        ]
        new_ver, supersedes_id, superseded_ids = _supersede_active_docs(
            tx, "assets", matching, asset.supersedes
        )
        minted = asset.model_copy(
            update={
                "id": f"{base_id}_v{new_ver}",
                "version": new_ver,
                "supersedes": supersedes_id,
            }
        )
        tx.set("assets", minted.id, encode(minted))

    _link_minted_asset_to_appearances(repo, minted, superseded_ids)
    for old_id in superseded_ids:
        propagate_staleness(repo, old_id, f"Asset {old_id} superseded by {minted.id}")
    return minted


def _try_resolve_appearance_id(repo: Repo, entity_id: str, story_order: int) -> str:
    from ..state import appearance_for

    if not entity_id:
        return ""
    try:
        return appearance_for(repo, entity_id, story_order).id
    except Exception:
        return ""


def _collect_shot_ref_ids(
    repo: Repo,
    loc_app_id: str,
    resolved_cast: list[CastInShot],
    prop_app_ids: dict[str, str],
) -> list[str]:
    ref_ids: list[str] = []
    if loc_app_id:
        ref_ids.append(loc_app_id)
    for c in resolved_cast:
        if c.appearance_id and c.appearance_id not in ref_ids:
            ref_ids.append(c.appearance_id)
    for paid in prop_app_ids.values():
        if paid and paid not in ref_ids:
            ref_ids.append(paid)
    for app_id in list(ref_ids):
        app_obj = repo.get_appearance(app_id)
        if app_obj:
            for aid in app_obj.asset_ids:
                if aid not in ref_ids:
                    ref_ids.append(aid)
    return ref_ids


def _resolve_shot_appearances(
    repo: Repo, shot: Shot
) -> tuple[str, list[CastInShot], dict[str, str]]:
    loc_app_id = shot.location_appearance_id or _try_resolve_appearance_id(
        repo, shot.location_id, shot.story_order
    )
    resolved_cast = [
        c.model_copy(
            update={
                "appearance_id": c.appearance_id
                or _try_resolve_appearance_id(repo, c.entity_id, shot.story_order)
            }
        )
        for c in shot.cast
    ]
    prop_app_ids = dict(shot.prop_appearance_ids)
    for pid in shot.prop_ids:
        if not prop_app_ids.get(pid):
            resolved_pid = _try_resolve_appearance_id(repo, pid, shot.story_order)
            if resolved_pid:
                prop_app_ids[pid] = resolved_pid
    return loc_app_id, resolved_cast, prop_app_ids


def persist_shot_with_refs(repo: Repo, shot: Shot) -> Shot:
    """Persist a Shot after deterministically resolving appearance_ids and denormalizing ref_ids."""
    existing = repo.get_shot(shot.id)
    next_ver = (existing.version + 1) if existing else 1
    loc_app_id, resolved_cast, prop_app_ids = _resolve_shot_appearances(repo, shot)
    ref_ids = _collect_shot_ref_ids(repo, loc_app_id, resolved_cast, prop_app_ids)
    updated = shot.model_copy(
        update={
            "version": next_ver,
            "location_appearance_id": loc_app_id,
            "cast": resolved_cast,
            "prop_appearance_ids": prop_app_ids,
            "ref_ids": ref_ids,
        }
    )
    repo.store.set("shots", updated.id, encode(updated))
    if existing and shot.content_hash and existing.content_hash != shot.content_hash:
        close_critic_change_requests(repo.store, shot.id, "spec_regenerated")
    scene = repo.get_scene(updated.scene_id)
    if scene and updated.id not in scene.shot_ids:
        repo.put_scene(
            scene.model_copy(update={"shot_ids": [*scene.shot_ids, updated.id]})
        )
    return updated


def propagate_staleness(repo: Repo, ref_id: str, reason: str) -> list[str]:
    rows = repo.store.query("shots", filters=[("ref_ids", "array_contains", ref_id)])
    if not rows:
        return []
    affected: list[str] = []
    with repo.store.batch() as b:
        for r in rows:
            shot = decode(r, Shot)
            updated = shot.model_copy(
                update={
                    "stale": True,
                    "stale_reason": reason,
                    "version": shot.version + 1,
                }
            )
            b.set("shots", updated.id, encode(updated))
            affected.append(updated.id)
    return affected

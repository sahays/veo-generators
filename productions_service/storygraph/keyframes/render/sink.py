"""Persist rendered keyframes and scene plates as `Asset`s linked to their shot/scene.

Writes are direct, idempotent document sets with content-addressed ids — no versioning
transaction. (`Repo.add_asset` scans the whole assets collection inside a transaction; with
scenes rendering in parallel those transactions contended and aborted whole scenes.)
* keyframe: `ast_kf_<shot>_<plan8>_t<tt>_<sha8>`; `qa_notes` = JSON link record (shot id,
  prompt version id, plan hash, second, attempts, issues, drift metrics).
* plate: `ast_plate_<scene>_<plate key>`; `qa_notes` = JSON {plate_key, layout, issues}, so
  an unchanged scene reuses its plate (same camera and furniture layout) on every run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from ...repo import Repo
from ...schema import Asset, Role, Status
from ...store.codec import encode
from ..plan.models import Keyframe, KeyframePlan
from ..plate.build import PlateImage
from ..plate.spec import PlateSpec


@dataclass(frozen=True)
class StoredKeyframe:
    asset_id: str
    uri: str


@dataclass(frozen=True)
class KeyframeRecord:
    """Everything needed to store one keyframe."""

    plan: KeyframePlan
    frame: Keyframe
    png: bytes
    prompt: str
    model: str
    attempts: int
    issues: tuple[str, ...]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredPlate:
    asset_id: str
    uri: str
    png: bytes
    layout: dict[str, float]
    issues: tuple[str, ...]


class KeyframeSink(Protocol):
    def save(self, record: KeyframeRecord) -> StoredKeyframe: ...

    def save_animatic(self, plan: KeyframePlan, mp4: bytes) -> StoredKeyframe: ...


class PlateStore(Protocol):
    def load_layout(self, spec: PlateSpec) -> dict[str, float]: ...

    def load_plate(self, spec: PlateSpec) -> StoredPlate | None: ...

    def save_plate(
        self, spec: PlateSpec, plate: PlateImage, model: str
    ) -> StoredPlate: ...


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plate_asset_id(spec: PlateSpec) -> str:
    return f"ast_plate_{spec.scene_id}_{spec.key}"


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _layout(notes: dict[str, object]) -> dict[str, float]:
    raw = notes.get("layout")
    if not isinstance(raw, dict):
        return {}
    return {str(k): float(v) for k, v in raw.items() if isinstance(v, int | float)}


class RepoKeyframeSink:
    """`KeyframeSink` + `PlateStore` backed by the project's `Repo` (blobs + assets)."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    def _put(self, rel: str, data: bytes, mime: str) -> str:
        return self.repo.blobs.put_bytes(rel, data, mime)

    def _write(self, asset: Asset) -> Asset:
        self.repo.store.set("assets", asset.id, encode(asset))
        return asset

    def save(self, record: KeyframeRecord) -> StoredKeyframe:
        plan, frame = record.plan, record.frame
        sha = _sha(record.png)
        stem = f"{plan.plan_hash[:8]}_t{frame.t:02d}_{sha[:8]}"
        uri = self._put(f"keyframes/{plan.shot_id}/{stem}.png", record.png, "image/png")
        link = {
            "shot_id": plan.shot_id,
            "prompt_version_id": plan.prompt_version_id,
            "plan_hash": plan.plan_hash,
            "t": frame.t,
            "attempts": record.attempts,
            "issues": list(record.issues),
            "metrics": record.metrics,
        }
        asset = self._write(
            Asset(
                id=f"ast_kf_{plan.shot_id}_{stem}",
                created_by=Role.PIPELINE,
                status=Status.PROPOSED if record.issues else Status.APPROVED,
                kind="keyframe",
                uri=uri,
                sha256=sha,
                depicts_entity_ids=[c.entity_id for c in frame.characters],
                generation_prompt=record.prompt,
                model=record.model,
                qa_notes=json.dumps(link),
            )
        )
        return StoredKeyframe(asset.id, asset.uri)

    def save_animatic(self, plan: KeyframePlan, mp4: bytes) -> StoredKeyframe:
        sha = _sha(mp4)
        rel = f"keyframes/{plan.shot_id}/{plan.plan_hash}/animatic_{sha[:8]}.mp4"
        asset = self._write(
            Asset(
                id=f"ast_animatic_{plan.shot_id}_{plan.plan_hash[:8]}_{sha[:8]}",
                created_by=Role.PIPELINE,
                status=Status.APPROVED,
                kind="animatic",
                uri=self._put(rel, mp4, "video/mp4"),
                sha256=sha,
                generation_prompt=f"1 fps animatic of plan {plan.plan_hash}",
                model="ffmpeg",
                qa_notes=json.dumps(
                    {"shot_id": plan.shot_id, "plan_hash": plan.plan_hash}
                ),
            )
        )
        return StoredKeyframe(asset.id, asset.uri)

    def _plate_asset(self, spec: PlateSpec) -> tuple[Asset, dict[str, object]] | None:
        asset = self.repo.get_asset(plate_asset_id(spec))
        if asset is None or not asset.uri:
            return None
        return asset, json.loads(asset.qa_notes or "{}")

    def load_layout(self, spec: PlateSpec) -> dict[str, float]:
        """The stored plate's layout (`set piece id -> x`); {} when no plate exists yet."""
        found = self._plate_asset(spec)
        return _layout(found[1]) if found else {}

    def load_plate(self, spec: PlateSpec) -> StoredPlate | None:
        """The stored plate for exactly this spec (same key), or None."""
        found = self._plate_asset(spec)
        if found is None:
            return None
        asset, notes = found
        png = self.repo.blobs.get_bytes(asset.uri)
        issues = tuple(str(i) for i in _as_list(notes.get("issues")))
        return StoredPlate(asset.id, asset.uri, png, _layout(notes), issues)

    def save_plate(self, spec: PlateSpec, plate: PlateImage, model: str) -> StoredPlate:
        sha = _sha(plate.png)
        rel = f"plates/{spec.scene_id}/{spec.key}_{sha[:8]}.png"
        notes = {
            "plate_key": spec.key,
            "layout": plate.layout,
            "issues": list(plate.issues),
        }
        asset = self._write(
            Asset(
                id=plate_asset_id(spec),
                created_by=Role.PIPELINE,
                status=Status.PROPOSED if plate.issues else Status.APPROVED,
                kind="scene_plate",
                uri=self._put(rel, plate.png, "image/png"),
                sha256=sha,
                depicts_entity_ids=[o.entity_id for o in spec.set_pieces],
                generation_prompt=plate.prompt,
                model=model,
                qa_notes=json.dumps(notes),
            )
        )
        return StoredPlate(asset.id, asset.uri, plate.png, plate.layout, plate.issues)

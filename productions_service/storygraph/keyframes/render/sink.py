"""Persist rendered keyframes as versioned `Asset`s linked to their shot and prompt version.

Asset ids are `ast_kf_<shot>_t<tt>` minted `_v1`, `_v2`... by `Repo.add_asset` (re-renders
supersede the previous version). `qa_notes` carries the JSON link record: shot id, prompt
version id, plan hash, second, attempts and the remaining check issues.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from ...repo import Repo
from ...schema import Asset, Role, Status
from ..plan.models import Keyframe, KeyframePlan


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


class KeyframeSink(Protocol):
    def save(self, record: KeyframeRecord) -> StoredKeyframe: ...

    def save_animatic(self, plan: KeyframePlan, mp4: bytes) -> StoredKeyframe: ...


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RepoKeyframeSink:
    """`KeyframeSink` backed by the project's `Repo` (blob store + assets collection)."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    def _put(self, rel: str, data: bytes, mime: str) -> str:
        return self.repo.blobs.put_bytes(rel, data, mime)

    def save(self, record: KeyframeRecord) -> StoredKeyframe:
        plan, frame = record.plan, record.frame
        sha = _sha(record.png)
        uri = self._put(
            f"keyframes/{plan.shot_id}/{plan.plan_hash}/t{frame.t:02d}_{sha[:8]}.png",
            record.png,
            "image/png",
        )
        link = {
            "shot_id": plan.shot_id,
            "prompt_version_id": plan.prompt_version_id,
            "plan_hash": plan.plan_hash,
            "t": frame.t,
            "attempts": record.attempts,
            "issues": list(record.issues),
        }
        asset = self.repo.add_asset(
            Asset(
                id=f"ast_kf_{plan.shot_id}_t{frame.t:02d}",
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
        uri = self._put(
            f"keyframes/{plan.shot_id}/{plan.plan_hash}/animatic_{sha[:8]}.mp4",
            mp4,
            "video/mp4",
        )
        asset = self.repo.add_asset(
            Asset(
                id=f"ast_animatic_{plan.shot_id}",
                created_by=Role.PIPELINE,
                status=Status.APPROVED,
                kind="animatic",
                uri=uri,
                sha256=sha,
                generation_prompt=f"1 fps animatic of plan {plan.plan_hash}",
                model="ffmpeg",
                qa_notes=json.dumps(
                    {"shot_id": plan.shot_id, "plan_hash": plan.plan_hash}
                ),
            )
        )
        return StoredKeyframe(asset.id, asset.uri)

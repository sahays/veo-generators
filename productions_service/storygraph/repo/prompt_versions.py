"""PromptVersion repository: immutable Omni spec versions per shot (`prompt_versions`).

Lookups are single indexed queries: by id (doc get), by `(shot_id, spec_hash)` for
dedupe, by `(shot_id, status=='active')` for the active version, and `shot_id` ordered by
`version` for lineage. Activation only rewrites the currently-active rows (normally one).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from ..errors import NotFound
from ..prompting.json_diff import diff_specs, spec_hash
from ..schema import (
    GenerationRun,
    PatchOp,
    PromptVersion,
    PromptVersionAuthor,
    PromptVersionStatus,
    Role,
)
from ..schemas.generation import PromptFormat
from ..store.base import Filter, GraphStore
from ..store.codec import decode, encode

logger = logging.getLogger(__name__)

COLLECTION: Final[str] = "prompt_versions"
_ROLE_BY_AUTHOR: Final[dict[str, Role]] = {
    "compiler": Role.PIPELINE,
    "prompt_doctor": Role.CRITIC,
    "human": Role.HUMAN,
}


@dataclass(frozen=True)
class PromptDraft:
    """Typed input for `PromptVersionRepo.create` (everything but id/version/hash)."""

    shot_id: str
    spec_json: str
    author: PromptVersionAuthor = "compiler"
    reason: str = ""
    parent_id: str | None = None
    shot_content_hash: str | None = None
    patch: list[PatchOp] | None = None
    rendered_prompt: str | None = (
        None  # text sent to Omni (None: rendered at render time)
    )
    prompt_format: PromptFormat | None = None


def _log(what: str, why: str, how: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.repo",
            "where": "repo.prompt_versions",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            **extra,
        },
    )


class PromptVersionRepo:
    """Typed access to the project's `prompt_versions` collection."""

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def _query(
        self,
        filters: list[Filter],
        order_by: str | None = None,
        limit: int | None = None,
    ) -> list[PromptVersion]:
        rows = self.store.query(
            COLLECTION, filters=filters, order_by=order_by, limit=limit
        )
        return [decode(r, PromptVersion) for r in rows]

    def _put(self, pv: PromptVersion) -> PromptVersion:
        self.store.set(COLLECTION, pv.id, encode(pv))
        return pv

    def get(self, version_id: str) -> PromptVersion | None:
        raw = self.store.get(COLLECTION, version_id)
        return decode(raw, PromptVersion) if raw else None

    def require(self, version_id: str) -> PromptVersion:
        pv = self.get(version_id)
        if pv is None:
            raise NotFound(f"PromptVersion {version_id} not found")
        return pv

    def list_for_shot(self, shot_id: str) -> list[PromptVersion]:
        """Every version of the shot, oldest first (lineage order)."""
        return self._query([("shot_id", "==", shot_id)], order_by="version")

    def active_for_shot(self, shot_id: str) -> PromptVersion | None:
        rows = self._query([("shot_id", "==", shot_id), ("status", "==", "active")])
        return max(rows, key=lambda pv: pv.version) if rows else None

    def active_by_shot(self) -> dict[str, PromptVersion]:
        """Active version per shot across the project in a single query."""
        return {pv.shot_id: pv for pv in self._query([("status", "==", "active")])}

    def find_by_hash(self, shot_id: str, digest: str) -> PromptVersion | None:
        rows = self._query(
            [("shot_id", "==", shot_id), ("spec_hash", "==", digest)], limit=1
        )
        return rows[0] if rows else None

    def _next_number(self, shot_id: str) -> int:
        latest = self._query([("shot_id", "==", shot_id)], order_by="-version", limit=1)
        return latest[0].version + 1 if latest else 1

    def _activate(self, pv: PromptVersion) -> PromptVersion:
        """Make `pv` the single active version; previously-active rows become superseded."""
        for other in self._query(
            [("shot_id", "==", pv.shot_id), ("status", "==", "active")]
        ):
            if other.id != pv.id:
                self._put(other.model_copy(update={"status": "superseded"}))
        return self._put(pv.model_copy(update={"status": "active"}))

    def _patch_for(self, draft: PromptDraft) -> list[PatchOp] | None:
        if draft.patch is not None or draft.parent_id is None:
            return draft.patch
        parent = self.get(draft.parent_id)
        return diff_specs(parent.spec_json, draft.spec_json) if parent else None

    def _refresh_rendered(self, pv: PromptVersion, draft: PromptDraft) -> PromptVersion:
        """Update the derived rendered text (never the spec) when it differs."""
        if draft.rendered_prompt is None or (
            pv.rendered_prompt == draft.rendered_prompt
            and pv.prompt_format == draft.prompt_format
        ):
            return pv
        return self._put(
            pv.model_copy(
                update={
                    "rendered_prompt": draft.rendered_prompt,
                    "prompt_format": draft.prompt_format,
                }
            )
        )

    def create(self, draft: PromptDraft, activate: bool = True) -> PromptVersion:
        """Store a new immutable version, or reuse the shot's version with the same spec hash."""
        digest = spec_hash(draft.spec_json)
        existing = self.find_by_hash(draft.shot_id, digest)
        if existing is not None:
            existing = self._refresh_rendered(existing, draft)
            reused = (
                self._activate(existing)
                if activate and existing.status != "active"
                else existing
            )
            _log(
                "prompt_version_reused",
                "identical spec hash",
                "dedupe by (shot_id, spec_hash)",
                shot_id=draft.shot_id,
                prompt_version_id=reused.id,
            )
            return reused
        number = self._next_number(draft.shot_id)
        pv = PromptVersion(
            id=f"pv_{draft.shot_id}_{number}",
            version=number,
            created_by=_ROLE_BY_AUTHOR[draft.author],
            status="superseded",
            shot_id=draft.shot_id,
            parent_id=draft.parent_id,
            spec_json=draft.spec_json,
            spec_hash=digest,
            author=draft.author,
            patch=self._patch_for(draft),
            reason=draft.reason,
            shot_content_hash=draft.shot_content_hash,
            rendered_prompt=draft.rendered_prompt,
            prompt_format=draft.prompt_format,
        )
        stored = self._activate(pv) if activate else self._put(pv)
        _log(
            "prompt_version_created",
            draft.reason or "new spec",
            f"author={draft.author}",
            shot_id=draft.shot_id,
            prompt_version_id=stored.id,
            parent_id=draft.parent_id,
        )
        return stored

    def set_status(self, version_id: str, status: PromptVersionStatus) -> PromptVersion:
        pv = self.require(version_id)
        if status == "active":
            return self._activate(pv)
        return self._put(pv.model_copy(update={"status": status}))

    def record_result(
        self,
        version_id: str,
        run_id: str,
        eval_score: float | None,
        summary: dict[str, Any] | None,
    ) -> PromptVersion:
        """Link a GenerationRun and its latest eval outcome to the version (spec untouched)."""
        pv = self.require(version_id)
        run_ids = pv.run_ids if run_id in pv.run_ids else [*pv.run_ids, run_id]
        updated = pv.model_copy(
            update={
                "run_ids": run_ids,
                "eval_score": eval_score,
                "eval_summary": summary,
            }
        )
        _log(
            "prompt_version_result_recorded",
            "post-QA eval",
            "append run_id + latest score",
            shot_id=pv.shot_id,
            prompt_version_id=version_id,
            run_id=run_id,
            eval_score=eval_score,
        )
        return self._put(updated)

    def rollback(self, shot_id: str, version_id: str) -> PromptVersion:
        """Re-activate an earlier version of `shot_id` (others superseded)."""
        pv = self.require(version_id)
        if pv.shot_id != shot_id:
            raise NotFound(
                f"PromptVersion {version_id} does not belong to shot {shot_id}"
            )
        activated = self._activate(pv)
        _log(
            "prompt_version_rolled_back",
            "explicit activation",
            "supersede active rows",
            shot_id=shot_id,
            prompt_version_id=version_id,
        )
        return activated

    def spec_for_run(self, run: GenerationRun) -> str:
        """Spec JSON a run was rendered from: the run's own copy, else its PromptVersion's,
        else `compiled_prompt` (legacy JSON-era runs sent the spec JSON itself)."""
        if run.spec_json:
            return run.spec_json
        pv = self.get(run.prompt_version_id) if run.prompt_version_id else None
        return pv.spec_json if pv else run.compiled_prompt

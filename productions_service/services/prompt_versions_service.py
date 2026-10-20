"""Prompt-version endpoints: list a shot's Omni spec lineage, roll back, author a human spec."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from storygraph.errors import NotFound
from storygraph.prompting.human_spec import SpecRejected, validate_human_spec
from storygraph.prompting.json_diff import diff_specs
from storygraph.repo import Repo
from storygraph.repo.prompt_versions import PromptDraft, PromptVersionRepo
from storygraph.schema import PromptVersion

from .runtime import get_repo, load_runtime_config

__all__ = [
    "HumanPromptPayload",
    "activate_shot_prompt",
    "create_human_shot_prompt",
    "list_shot_prompts",
]
logger = logging.getLogger(__name__)


class HumanPromptPayload(BaseModel):
    """Human-authored OmniClipSpec (object or JSON string) and why it was written."""

    spec: dict[str, Any] | str
    reason: str = Field(default="human edit", max_length=500)


def _log(what: str, why: str, project_id: str, shot_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": "productions_service",
            "where": "services.prompt_versions_service",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "PromptVersionRepo",
            "project_id": project_id,
            "shot_id": shot_id,
            **extra,
        },
    )


def _repo(project_id: str, shot_id: str) -> Repo:
    repo = get_repo(project_id, cfg=load_runtime_config())
    if not repo.get_project_meta():
        raise HTTPException(status_code=404, detail="Production not found")
    if repo.get_shot(shot_id) is None:
        raise HTTPException(status_code=404, detail=f"Shot {shot_id} not found")
    return repo


def _serialize(pv: PromptVersion, by_id: dict[str, PromptVersion]) -> dict[str, Any]:
    out = pv.model_dump(mode="json")
    parent = by_id.get(pv.parent_id) if pv.parent_id else None
    patch = (
        pv.patch
        if pv.patch is not None
        else (diff_specs(parent.spec_json, pv.spec_json) if parent else [])
    )
    out["diff"] = [op.model_dump(mode="json") for op in patch]
    return out


def _listing(repo: Repo, shot_id: str) -> dict[str, Any]:
    versions = PromptVersionRepo(repo.store).list_for_shot(shot_id)
    by_id = {pv.id: pv for pv in versions}
    active = next((pv.id for pv in reversed(versions) if pv.status == "active"), None)
    return {
        "shot_id": shot_id,
        "active_version_id": active,
        "versions": [_serialize(pv, by_id) for pv in versions],
    }


def list_shot_prompts(project_id: str, shot_id: str) -> dict[str, Any]:
    """Every PromptVersion of the shot (oldest first) with its diff vs parent."""
    return _listing(_repo(project_id, shot_id), shot_id)


def activate_shot_prompt(
    project_id: str, shot_id: str, version_id: str
) -> dict[str, Any]:
    """Roll the shot back (or forward) to `version_id`; the next render uses it."""
    repo = _repo(project_id, shot_id)
    try:
        PromptVersionRepo(repo.store).rollback(shot_id, version_id)
    except NotFound as nf:
        raise HTTPException(status_code=404, detail=str(nf)) from nf
    _log(
        "prompt_version_activated",
        "user rollback",
        project_id,
        shot_id,
        prompt_version_id=version_id,
    )
    return _listing(repo, shot_id)


def create_human_shot_prompt(
    project_id: str, shot_id: str, body: HumanPromptPayload
) -> dict[str, Any]:
    """Validate (schema + lint) and store a human spec as the shot's active version."""
    repo = _repo(project_id, shot_id)
    try:
        validated = validate_human_spec(repo, shot_id, body.spec)
    except SpecRejected as rej:
        raise HTTPException(status_code=422, detail={"issues": rej.issues}) from rej
    versions = PromptVersionRepo(repo.store)
    active = versions.active_for_shot(shot_id)
    shot = repo.get_shot(shot_id)
    pv = versions.create(
        PromptDraft(
            shot_id=shot_id,
            spec_json=validated.spec_json,
            author="human",
            reason=body.reason,
            parent_id=active.id if active else None,
            shot_content_hash=shot.content_hash if shot else None,
        )
    )
    _log(
        "human_prompt_version_created",
        body.reason,
        project_id,
        shot_id,
        prompt_version_id=pv.id,
    )
    listing = _listing(repo, shot_id)
    listing["created_version_id"] = pv.id
    listing["warnings"] = [
        {"code": w.code, "message": w.message} for w in validated.warnings
    ]
    return listing

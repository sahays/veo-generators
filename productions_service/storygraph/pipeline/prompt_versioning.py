"""Pipeline glue for Omni prompt versioning (compile -> PromptVersion -> run -> QA result).

Every compiled spec sent to Omni is stored as a `PromptVersion`. A shot whose active
version was authored by the prompt doctor or a human renders THAT spec instead of the
fresh compile, unless the shot's render content changed since (content_hash), in which
case the fresh compiler spec supersedes it.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from ..compile import Package
from ..repo import Repo
from ..repo.prompt_versions import PromptDraft, PromptVersionRepo
from ..schema import GenerationRun, PromptVersion, QAReport, Shot

logger = logging.getLogger(__name__)
_P = TypeVar("_P", bound=Package)
_FALLBACK_SCORE_FIELDS: tuple[str, ...] = (
    "action_achieved",
    "physics_plausibility",
    "object_permanence",
    "wardrobe_match",
    "setting_match",
    "camera_match",
)


@dataclass(frozen=True)
class VersionedPackage(Generic[_P]):
    """Render package whose `compiled_prompt` is exactly the `version.spec_json`."""

    package: _P
    version: PromptVersion


def _log(repo: Repo, shot_id: str, what: str, why: str, pv: PromptVersion) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.pipeline.prompt_versioning",
            "where": "prompt_versioning.resolve_package",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": f"PromptVersion {pv.id} (author={pv.author}, v{pv.version})",
            "project_id": repo.project_id,
            "shot_id": shot_id,
            "prompt_version_id": pv.id,
        },
    )


def _override_applies(active: PromptVersion | None, shot: Shot) -> bool:
    """An active non-compiler version wins while the shot content it targeted is unchanged."""
    return (
        active is not None
        and active.author != "compiler"
        and active.shot_content_hash == shot.content_hash
    )


def _with_spec(pkg: _P, pv: PromptVersion) -> _P:
    """Swap the compiled prompt for the version's spec; re-derive the package hash."""
    digest = hashlib.sha256(f"{pkg.package_hash}:{pv.spec_hash}".encode()).hexdigest()
    return replace(pkg, compiled_prompt=pv.spec_json, package_hash=digest)


def resolve_package(
    repo: Repo, shot: Shot, pkg: _P, reason: str = "compiled"
) -> VersionedPackage[_P]:
    """Return the package to render for `shot` plus the PromptVersion it corresponds to."""
    versions = PromptVersionRepo(repo.store)
    active = versions.active_for_shot(shot.id)
    if active is not None and _override_applies(active, shot):
        _log(
            repo,
            shot.id,
            "prompt_version_override_used",
            "active non-compiler version",
            active,
        )
        return VersionedPackage(_with_spec(pkg, active), active)
    why = (
        reason
        if active is None or active.author == "compiler"
        else "shot content changed"
    )
    pv = versions.create(
        PromptDraft(
            shot_id=shot.id,
            spec_json=pkg.compiled_prompt,
            author="compiler",
            reason=why,
            parent_id=active.id if active else None,
            shot_content_hash=shot.content_hash,
        )
    )
    return VersionedPackage(pkg, pv)


def summarize_report(report: QAReport | None) -> tuple[float | None, dict[str, Any]]:
    """Overall score + per-dimension summary, tolerant of older/partial QAReport shapes."""
    if report is None:
        return None, {}
    dims = {
        str(getattr(d, "dimension", "")): float(getattr(d, "score", 0.0))
        for d in (getattr(report, "dimension_scores", None) or [])
    }
    overall = getattr(report, "eval_overall", None)
    if overall is None:
        vals = [
            float(getattr(report, f))
            for f in _FALLBACK_SCORE_FIELDS
            if hasattr(report, f)
        ]
        overall = sum(vals) / len(vals) if vals else None
    summary: dict[str, Any] = {
        "passed": bool(getattr(report, "passed", False)),
        "dimensions": dims,
        "failure_reasons": list(getattr(report, "failure_reasons", []) or []),
        "artifact_flags": list(getattr(report, "artifact_flags", []) or []),
    }
    return (float(overall) if overall is not None else None), summary


def record_run_result(repo: Repo, run: GenerationRun, report: QAReport | None) -> None:
    """Attach the run and its QA outcome to the PromptVersion it was rendered from."""
    if not run.prompt_version_id:
        return
    score, summary = summarize_report(report)
    PromptVersionRepo(repo.store).record_result(
        run.prompt_version_id, run.id, score, summary
    )

"""S6: review upstream artifacts, redo responsible stages, and never dead-end.

Per round: stage QA + remediation → state rebuild → deterministic validation fixes →
re-validate. Remaining errors route to authoring:
* species / vocalization (`S2_CLIP_SPECIES_ACTION`, `S2_CLIP_MUTE_SPEAKER`) → the
  Screenwriter rewrites ONLY the affected scene with the exact rule message as feedback
  (then the Director re-blocks that scene);
* everything else → `stages_to_redo_for_issues` (whole-stage redo, as before).
After `max_iterations`, a final deterministic pass runs; unrenderable shots (no location,
no cast for character actions, empty spec) raise `ValidationFailed` naming shot + reason;
every other error is demoted to a warning on the affected shots and recorded in an
`S6_VALIDATE` StageQaReport, and the pipeline continues.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..adapters.mock import MockLLMClient
from ..agents.roles import run_director_for_scene, run_screenwriter_for_scene
from ..agents.stage_qa import run_stage_qa_and_remediate, stages_to_redo_for_issues
from ..clips.species_validation import SPECIES_CODES
from ..config import Config
from ..errors import ValidationFailed
from ..repo import Repo
from ..schema import Role, StageQaIssue, StageQaReport, Status
from ..state import rebuild_state_facts
from ..tools.registry import ToolContext
from ..validate import ValidationIssue, validate_all
from ..validation.demotion import demote_to_shots
from ..validation.remediate import remediate_validation
from ..validation.renderable import unrenderable_issues

_log = logging.getLogger(__name__)
_S6 = "S6_VALIDATE"


@dataclass(frozen=True)
class ValidateStageDeps:
    """Typed input contract for S6 (`redo_stages` re-runs whole authoring stages)."""

    repo: Repo
    cfg: Config
    redo_stages: Callable[[list[str]], None]
    language: str = "en"
    mock_llm: MockLLMClient | None = None


@dataclass
class ValidateOutcome:
    """Typed output: what was fixed, rewritten and demoted."""

    rounds: int = 0
    fixes: list[str] = field(default_factory=list)
    rewritten_scenes: list[str] = field(default_factory=list)
    demoted: list[ValidationIssue] = field(default_factory=list)


def _log_event(deps: ValidateStageDeps, what: str, why: str, how: str) -> None:
    _log.info(
        "s6_validate_stage",
        extra={
            "who": "pipeline.validate_stage",
            "where": f"project:{deps.repo.project_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
        },
    )


def _errors(deps: ValidateStageDeps, out: ValidateOutcome) -> list[ValidationIssue]:
    """Validate, apply deterministic fixes, re-validate; returns remaining errors."""
    errs = [i for i in validate_all(deps.repo, deps.cfg) if i.severity == "error"]
    fixes = remediate_validation(deps.repo, deps.cfg, errs)
    if not fixes:
        return errs
    out.fixes.extend(fixes)
    return [i for i in validate_all(deps.repo, deps.cfg) if i.severity == "error"]


def _rewrite_scene(deps: ValidateStageDeps, scene_id: str, feedback: list[str]) -> None:
    sw = ToolContext(repo=deps.repo, role=Role.SCREENWRITER, cfg=deps.cfg)
    run_screenwriter_for_scene(sw, scene_id, deps.language, deps.mock_llm, feedback)
    dr = ToolContext(repo=deps.repo, role=Role.DIRECTOR, cfg=deps.cfg)
    run_director_for_scene(dr, scene_id, deps.mock_llm, ())


def rewrite_species_scenes(
    deps: ValidateStageDeps, issues: list[ValidationIssue]
) -> list[str]:
    """Scene-scoped Screenwriter rewrite with the species rule messages as feedback."""
    by_scene: dict[str, list[str]] = {}
    for i in issues:
        by_scene.setdefault(i.node_id, []).append(i.message)
    if not by_scene:
        return []
    with ThreadPoolExecutor(max_workers=len(by_scene)) as pool:
        futs = [pool.submit(_rewrite_scene, deps, s, fb) for s, fb in by_scene.items()]
        for fut in futs:
            fut.result()
    rebuild_state_facts(deps.repo)
    _log_event(
        deps,
        f"rewrote scenes {sorted(by_scene)}",
        f"{len(issues)} species/vocalization rule violations",
        "screenwriter per scene with rule messages as feedback, then director",
    )
    return sorted(by_scene)


def _route(
    deps: ValidateStageDeps,
    qa: StageQaReport,
    errs: list[ValidationIssue],
    out: ValidateOutcome,
) -> None:
    species = [e for e in errs if e.code in SPECIES_CODES]
    others = [e for e in errs if e.code not in SPECIES_CODES]
    out.rewritten_scenes.extend(rewrite_species_scenes(deps, species))
    qa_others = [i for i in qa.issues if i.code not in SPECIES_CODES]
    open_crs = deps.repo.list_change_requests(open_only=True)
    deps.redo_stages(stages_to_redo_for_issues(qa_others, others, open_crs))
    for cr in open_crs:
        deps.repo.resolve_change_request(cr.id, "accepted")


def review_and_redo(
    deps: ValidateStageDeps, max_iterations: int = 3
) -> ValidateOutcome:
    """Run S6 rounds; returns the outcome or raises only for unrenderable shots."""
    out = ValidateOutcome()
    for attempt in range(1, max_iterations + 1):
        out.rounds = attempt
        qa = run_stage_qa_and_remediate(
            deps.repo, deps.cfg, "S5_MUSIC", max_iterations=max_iterations
        )
        rebuild_state_facts(deps.repo)
        errs = _errors(deps, out)
        open_crs = deps.repo.list_change_requests(open_only=True)
        if (qa.passed and not errs and not open_crs) or attempt == max_iterations:
            break
        _route(deps, qa, errs, out)
    return finalize(deps, out)


def finalize(deps: ValidateStageDeps, out: ValidateOutcome) -> ValidateOutcome:
    """Block only on unrenderable shots; demote every other error to shot warnings."""
    rebuild_state_facts(deps.repo)
    errs = _errors(deps, out)
    blocking = unrenderable_issues(deps.repo)
    out.demoted = errs
    reason = f"not fixed after {out.rounds} S6 round(s); demoted so rendering continues"
    demote_to_shots(deps.repo, errs, reason)
    _record_report(deps, out, blocking)
    if blocking:
        raise ValidationFailed([f"{i.code} {i.node_id}: {i.message}" for i in blocking])
    return out


def _record_report(
    deps: ValidateStageDeps, out: ValidateOutcome, blocking: list[ValidationIssue]
) -> None:
    issues = [
        StageQaIssue(
            code=i.code,
            severity=sev,
            node_id=i.node_id,
            dimension="validation",
            message=i.message,
        )
        for sev, group in (("error", blocking), ("warn", out.demoted))
        for i in group
    ]
    report = StageQaReport(
        id=f"sqa_{_S6}_{uuid.uuid4().hex[:8]}",
        created_by=Role.CRITIC,
        status=Status.APPROVED if not blocking else Status.NEEDS_REVISION,
        stage=_S6,
        iteration=max(1, out.rounds),
        passed=not blocking,
        score=1.0 if not issues else max(0.0, round(1.0 - 0.05 * len(issues), 2)),
        issues=issues,
        remediation_applied=[
            *out.fixes,
            *(f"rewrote {s}" for s in out.rewritten_scenes),
        ],
        summary=f"S6: {len(blocking)} unrenderable, {len(out.demoted)} demoted to warnings, {len(out.fixes)} auto-fixed.",
    )
    deps.repo.store.set("stage_qa_reports", report.id, report.model_dump(mode="json"))
    _log_event(
        deps,
        report.summary,
        "S6 must not dead-end on renderable shots",
        "unrenderable block + demotion",
    )

"""S7 compile + blocking spec lint: deterministic remediation, then scene-scoped LLM redo.

Order per round:
1. compile every shot and lint the specs;
2. deterministic fixes (`lint.remediate`): split overloaded clips / move overflow dialogue →
   director re-map of the touched scenes → camera adjustments; re-lint after each change;
3. record open + auto-fixed issues on every shot (`Shot.lint_issues`);
4. if blocking issues remain, re-run S2 (screenwriter, then director) or S4 (director) ONLY
   for the affected scenes with the exact lint messages as prompt feedback.
After `max_llm_rounds` redo rounds the remaining issues are demoted to shot warnings
(`status="demoted"`); only unrenderable shots raise `ValidationFailed` (no dead ends).
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..adapters.base import VideoGenerator
from ..adapters.mock import MockLLMClient
from ..agents.role.director_remap import remap_scene_shots
from ..agents.roles import run_director_for_scene, run_screenwriter_for_scene
from ..compile import Package
from ..config import Config
from ..errors import ValidationFailed
from ..lint.feedback import SceneFeedback, record_shot_lint, scene_feedback
from ..lint.models import LintIssue, blocking
from ..lint.remediate import AppliedFix, fix_cameras, fix_clip_load, rekey_fixes
from ..lint.spec_lint import lint_packages
from ..repo import Repo
from ..schema import Role
from ..state import rebuild_state_facts
from ..tools.registry import ToolContext
from ..validation.renderable import unrenderable_issues
from .render_stage import compile_all_shots

_log = logging.getLogger(__name__)
MAX_LLM_ROUNDS: int = 2


@dataclass(frozen=True)
class LintStageDeps:
    """Typed input contract for the S7 stage."""

    repo: Repo
    cfg: Config
    video_gen: VideoGenerator
    language: str = "en"
    mock_llm: MockLLMClient | None = None


@dataclass
class LintPass:
    """One compile + lint result and the deterministic fixes applied so far."""

    packages: dict[str, Package]
    issues: list[LintIssue]
    fixes: list[AppliedFix] = field(default_factory=list)


def _log_event(what: str, why: str, how: str, deps: LintStageDeps) -> None:
    _log.info(
        "s7_lint_stage",
        extra={
            "who": "pipeline.lint_stage",
            "where": f"project:{deps.repo.project_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
        },
    )


def lint_pass(deps: LintStageDeps, fixes: list[AppliedFix]) -> LintPass:
    packages = compile_all_shots(deps.repo, deps.cfg, deps.video_gen)
    return LintPass(packages, lint_packages(deps.repo, packages), fixes)


def _remap(deps: LintStageDeps, remap: dict[str, dict[int, int | None]]) -> None:
    ctx = ToolContext(repo=deps.repo, role=Role.DIRECTOR, cfg=deps.cfg)
    for scene_id, origin in remap.items():
        remap_scene_shots(ctx, scene_id, origin, deps.mock_llm)
    rebuild_state_facts(deps.repo)


def remediate_pass(deps: LintStageDeps, lp: LintPass) -> LintPass:
    """Deterministic fixes for `lp`'s blocking issues; returns the re-linted pass."""
    load = fix_clip_load(deps.repo, blocking(lp.issues))
    fixes = [*lp.fixes, *load.fixes]
    if load.remap:
        _remap(deps, load.remap)
        fixes = rekey_fixes(deps.repo, fixes)
        lp = lint_pass(deps, fixes)
    cams = fix_cameras(deps.repo, blocking(lp.issues))
    if cams.fixes:
        lp = lint_pass(deps, [*fixes, *cams.fixes])
    lp.fixes = [*fixes, *cams.fixes]
    _log_event(
        f"{len(lp.fixes)} deterministic fixes, {len(blocking(lp.issues))} blocking left",
        "repair spec-lint errors without spending LLM or render budget",
        "clip split / dialogue move + director re-map + camera adjustment",
        deps,
    )
    return lp


def _redo_scene(deps: LintStageDeps, scene_id: str, fb: SceneFeedback) -> None:
    if fb.needs_screenwriter:
        sw = ToolContext(repo=deps.repo, role=Role.SCREENWRITER, cfg=deps.cfg)
        run_screenwriter_for_scene(
            sw, scene_id, deps.language, deps.mock_llm, fb.screenwriter
        )
    dr = ToolContext(repo=deps.repo, role=Role.DIRECTOR, cfg=deps.cfg)
    run_director_for_scene(dr, scene_id, deps.mock_llm, fb.director)


def llm_redo(deps: LintStageDeps, errors: list[LintIssue]) -> list[str]:
    """Re-author only the affected scenes with lint feedback; returns the scene ids."""
    feedback = scene_feedback(deps.repo, errors)
    with ThreadPoolExecutor(max_workers=max(1, len(feedback))) as pool:
        futs = [pool.submit(_redo_scene, deps, s, fb) for s, fb in feedback.items()]
        for fut in futs:
            fut.result()
    rebuild_state_facts(deps.repo)
    _log_event(
        f"re-authored scenes {sorted(feedback)}",
        f"{len(errors)} blocking lint issues survived deterministic remediation",
        "screenwriter (S2 issues) then director per scene, lint messages as feedback",
        deps,
    )
    return sorted(feedback)


def compile_and_lint(
    deps: LintStageDeps, max_llm_rounds: int = MAX_LLM_ROUNDS
) -> dict[str, Package]:
    """Run S7; return compiled packages or raise `ValidationFailed` with the issue list."""
    rebuild_state_facts(
        deps.repo
    )  # specs must never compile against stale clip windows
    fixes: list[AppliedFix] = []
    for rnd in range(max_llm_rounds + 1):
        lp = remediate_pass(deps, lint_pass(deps, fixes))
        fixes = lp.fixes
        errors = blocking(lp.issues)
        final = rnd == max_llm_rounds
        record_shot_lint(deps.repo, lp.issues, fixes, demoted=final)
        if not errors:
            return lp.packages
        if final:
            return _demote_or_block(deps, lp, errors)
        llm_redo(deps, errors)
    raise ValidationFailed([])  # unreachable: the loop returns or raises


def _demote_or_block(
    deps: LintStageDeps, lp: LintPass, errors: list[LintIssue]
) -> dict[str, Package]:
    """No dead ends: only unrenderable shots block; other lint errors were demoted."""
    blocking_shots = unrenderable_issues(deps.repo)
    if blocking_shots:
        raise ValidationFailed(
            [f"{i.code} {i.node_id}: {i.message}" for i in blocking_shots]
        )
    _log_event(
        f"demoted {len(errors)} lint errors on {len({e.shot_id for e in errors})} shots",
        "remediation rounds exhausted; lint findings are quality issues, not unrenderable",
        "Shot.lint_issues status=demoted severity=warn",
        deps,
    )
    return lp.packages

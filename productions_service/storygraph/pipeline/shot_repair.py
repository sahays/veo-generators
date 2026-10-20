"""Automatic QA repair of a failing shot: up to `MAX_REPAIR_ATTEMPTS` routed repairs.

After the normal attempts fail, each repair attempt first classifies the latest failed QA
(`pipeline.repair_route`):
- *spec*-caused: regenerate THIS clip's spec (screenwriter + director, clip-scoped), then
  render it fresh. Falls back to the render route when nothing in the spec changed.
- *render*-caused: diagnose a `RepairDirective` (attempt 1 targeted, attempt 2 escalated)
  and re-render with a new seed.
If the shot still fails it is flagged `needs_manual_edit` with concise reasons.
`Shot.repair_attempts` is incremented *before* each repair so the per-content-version
budget can never be exceeded, even across crashes, concurrent requests or spec changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..qa.llm_rewrite import make_llm_rewriter
from ..qa.retry_rewrite import context_from_view
from ..repair import (
    MAX_REPAIR_ATTEMPTS,
    RepairDirective,
    RepairRoute,
    RouteDecision,
    ShotRepairOutcome,
    diagnose_failure,
    manual_edit_reasons,
)
from ..schema import QAReport, Shot, Status
from ..views import shot_view
from .repair_route import decide_route, regenerate_spec
from .shot_attempt import (
    RenderDeps,
    latest_current_run,
    next_attempt_number,
    render_attempt,
)

logger = logging.getLogger(__name__)
_WHO = "storygraph.pipeline.shot_repair"


def _log(what: str, why: str, how: str, shot_id: str, **extra: Any) -> None:
    logger.info(
        what,
        extra={
            "who": _WHO,
            "where": f"shot_repair:{shot_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            "shot_id": shot_id,
            **extra,
        },
    )


@dataclass(frozen=True)
class _RepairStep:
    """The next repair attempt: its number, route decision and the QA it repairs."""

    attempt: int
    decision: RouteDecision
    report: QAReport


@dataclass
class RepairRun:
    """Result of the repair attempts for one shot."""

    passed: bool = False
    renders: int = 0
    routes: list[RepairRoute] = field(default_factory=list)


def _current(deps: RenderDeps, shot_id: str) -> Shot:
    shot = deps.repo.get_shot(shot_id)
    if shot is None:
        raise KeyError(f"shot {shot_id} disappeared during repair")
    return shot


def should_drop_last_frame(deps: RenderDeps, shot_id: str) -> bool:
    """True only when the latest failed run exhibited first-frame corruption or freeze."""
    runs = deps.repo.list_generation_runs(shot_id=shot_id)
    if not runs or runs[-1].status != Status.FAILED or not runs[-1].qa_scores:
        return False
    flags = set(runs[-1].qa_scores.artifact_flags)
    return bool({"frozen_frame", "corrupted_first_frame"} & flags)


def _next_step(deps: RenderDeps, shot: Shot) -> _RepairStep | None:
    """The shot's next repair attempt, or None when no repair applies (cap / no failure)."""
    if shot.repair_attempts >= MAX_REPAIR_ATTEMPTS:
        return None
    run = latest_current_run(deps.repo, shot)
    if run is None or run.qa_scores is None or run.qa_scores.passed:
        return None
    return _RepairStep(
        shot.repair_attempts + 1, decide_route(deps, shot, run), run.qa_scores
    )


def _directive(deps: RenderDeps, shot: Shot, step: _RepairStep) -> RepairDirective:
    llm = make_llm_rewriter(deps.vlm) if deps.cfg.qa.retry_rewrite_llm else None
    ctx = context_from_view(shot_view(deps.repo, shot.id))
    return diagnose_failure(step.report, ctx, deps.cfg.qa, step.attempt, llm)


def _spec_route(deps: RenderDeps, shot_id: str, step: _RepairStep) -> bool | None:
    """Regenerate the clip spec and render it; None when the spec did not change."""
    result = regenerate_spec(deps, shot_id, step.report, step.decision)
    if result is None or not result.changed:
        _log(
            "spec_route_fallback",
            "clip spec unchanged after regeneration",
            "render route",
            shot_id,
        )
        return None
    attempt_no = next_attempt_number(deps.repo, shot_id)
    return render_attempt(deps, _current(deps, shot_id), attempt_no, False)


def _execute(
    deps: RenderDeps, shot_id: str, step: _RepairStep
) -> tuple[bool, RepairRoute]:
    """Run one repair attempt (budget charged first); return (passed, route taken)."""
    shot = deps.repo.put_shot(
        _current(deps, shot_id).model_copy(update={"repair_attempts": step.attempt})
    )
    _log(
        "shot_repair_attempt",
        step.decision.why,
        f"attempt={step.attempt} route={step.decision.route}",
        shot_id,
        evidence=step.decision.evidence[:6],
    )
    if step.decision.route == "spec":
        passed = _spec_route(deps, shot_id, step)
        if passed is not None:
            return passed, "spec"
        shot = _current(deps, shot_id)
    directive = _directive(deps, shot, step)
    _log(
        "shot_repair_directive",
        f"QA failed: {[c.value for c in directive.failure_classes]}",
        f"escalated={directive.escalated}",
        shot_id,
        directive=directive.model_dump(mode="json"),
    )
    attempt_no = next_attempt_number(deps.repo, shot_id)
    return render_attempt(deps, shot, attempt_no, False, repair=directive), "render"


def run_repair_attempts(deps: RenderDeps, shot_id: str) -> RepairRun:
    """Run the remaining repair attempts; stop at the first QA pass."""
    out = RepairRun()
    while (step := _next_step(deps, _current(deps, shot_id))) is not None:
        passed, route = _execute(deps, shot_id, step)
        out.renders += 1
        out.routes.append(route)
        if passed:
            out.passed = True
            break
    return out


def flag_for_manual_edit(deps: RenderDeps, shot_id: str) -> list[str]:
    """Mark the shot `needs_manual_edit` with concise reasons from its latest QA verdict."""
    shot = _current(deps, shot_id)
    run = latest_current_run(deps.repo, shot)
    reasons = manual_edit_reasons(run.qa_scores if run else None)
    deps.repo.put_shot(
        shot.model_copy(
            update={"needs_manual_edit": True, "manual_edit_reasons": reasons}
        )
    )
    _log(
        "shot_flagged_for_manual_edit",
        "; ".join(reasons),
        f"exhausted {MAX_REPAIR_ATTEMPTS} repair attempts",
        shot_id,
        project_id=deps.repo.project_id,
    )
    return reasons


def _initial_attempts(deps: RenderDeps, shot_id: str, count: int) -> tuple[bool, int]:
    for done in range(1, count + 1):
        shot = _current(deps, shot_id)
        attempt_no = next_attempt_number(deps.repo, shot_id)
        if render_attempt(
            deps, shot, attempt_no, should_drop_last_frame(deps, shot_id)
        ):
            return True, done
    return False, count


def render_with_repairs(
    deps: RenderDeps, shot_id: str, initial_attempts: int
) -> ShotRepairOutcome:
    """`initial_attempts` normal renders, then up to the remaining repairs, else flag.

    Worst-case renders per shot = initial_attempts + MAX_REPAIR_ATTEMPTS (logged).
    """
    passed, renders = _initial_attempts(deps, shot_id, initial_attempts)
    repairs = RepairRun(passed=passed)
    if not passed:
        repairs = run_repair_attempts(deps, shot_id)
        renders += repairs.renders
    reasons = [] if repairs.passed else flag_for_manual_edit(deps, shot_id)
    final = _current(deps, shot_id)
    _log(
        "shot_render_with_repairs_done",
        "approved" if repairs.passed else "flagged for manual edit",
        f"renders={renders} cap={initial_attempts + MAX_REPAIR_ATTEMPTS} routes={repairs.routes}",
        shot_id,
        renders=renders,
        repair_attempts=final.repair_attempts,
    )
    return ShotRepairOutcome(
        shot_id=shot_id,
        outcome="approved" if repairs.passed else "flagged",
        renders=renders,
        repair_attempts=final.repair_attempts,
        reasons=reasons,
        routes=repairs.routes,
    )

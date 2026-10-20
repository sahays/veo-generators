"""Automatic QA repair of a failing shot: up to `MAX_REPAIR_ATTEMPTS` directed re-renders.

After the normal attempts fail, each repair attempt diagnoses the latest failed QA into a
`RepairDirective` (attempt 1 targeted, attempt 2 escalated) and re-renders with a new seed.
If the shot still fails it is flagged `needs_manual_edit` with concise reasons.
`Shot.repair_attempts` is incremented *before* each render so the per-content-version
budget can never be exceeded, even across crashes or concurrent requests.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ..qa.llm_rewrite import make_llm_rewriter
from ..qa.retry_rewrite import context_from_view
from ..repair import (
    MAX_REPAIR_ATTEMPTS,
    RepairDirective,
    ShotRepairOutcome,
    diagnose_failure,
    manual_edit_reasons,
)
from ..schema import Shot, Status
from ..views import shot_view
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


def _next_directive(deps: RenderDeps, shot: Shot) -> RepairDirective | None:
    """Directive for the shot's next repair attempt, or None when no repair applies."""
    if shot.repair_attempts >= MAX_REPAIR_ATTEMPTS:
        return None
    run = latest_current_run(deps.repo, shot)
    if run is None or run.qa_scores is None or run.qa_scores.passed:
        return None
    llm = make_llm_rewriter(deps.vlm) if deps.cfg.qa.retry_rewrite_llm else None
    ctx = context_from_view(shot_view(deps.repo, shot.id))
    return diagnose_failure(
        run.qa_scores, ctx, deps.cfg.qa, shot.repair_attempts + 1, llm
    )


def run_repair_attempts(deps: RenderDeps, shot_id: str) -> tuple[bool, int]:
    """Run the remaining repair attempts; stop at the first QA pass. Returns (passed, renders)."""
    renders = 0
    while (directive := _next_directive(deps, _current(deps, shot_id))) is not None:
        shot = deps.repo.put_shot(
            _current(deps, shot_id).model_copy(
                update={"repair_attempts": directive.attempt}
            )
        )
        _log(
            "shot_repair_attempt",
            f"QA failed: {[c.value for c in directive.failure_classes]}",
            f"directive attempt={directive.attempt} escalated={directive.escalated}",
            shot_id,
            directive=directive.model_dump(mode="json"),
        )
        renders += 1
        attempt_no = next_attempt_number(deps.repo, shot_id)
        if render_attempt(deps, shot, attempt_no, False, repair=directive):
            return True, renders
    return False, renders


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
    if not passed:
        passed, repairs = run_repair_attempts(deps, shot_id)
        renders += repairs
    reasons = [] if passed else flag_for_manual_edit(deps, shot_id)
    final = _current(deps, shot_id)
    _log(
        "shot_render_with_repairs_done",
        "approved" if passed else "flagged for manual edit",
        f"renders={renders} cap={initial_attempts + MAX_REPAIR_ATTEMPTS}",
        shot_id,
        renders=renders,
        repair_attempts=final.repair_attempts,
    )
    return ShotRepairOutcome(
        shot_id=shot_id,
        outcome="approved" if passed else "flagged",
        renders=renders,
        repair_attempts=final.repair_attempts,
        reasons=reasons,
    )

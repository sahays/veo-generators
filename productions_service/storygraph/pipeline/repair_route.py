"""Route a failed shot's next repair: regenerate its clip spec, or re-render with a directive.

Gathers the evidence `repair.classify_route` needs (failed-attempt history of the current
content version, blocking spec-linter issues) and runs the clip-scoped spec regeneration
when the failure is spec-caused. The Phase-1 spec linter is optional at runtime: it is
imported lazily and any absence or failure degrades to "no lint evidence".
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Final

from ..agents.role.clip_respec import ClipRespecResult, respec_clip_for_shot
from ..errors import NotFound
from ..repair import (
    RouteDecision,
    classify_route,
    manual_edit_reasons,
    spec_defect_texts,
)
from ..schema import GenerationRun, QAReport, Shot, Status
from ..shots import run_matches_shot
from .shot_attempt import RenderDeps

logger = logging.getLogger(__name__)
_WHO: Final[str] = "storygraph.pipeline.repair_route"
_BLOCKING_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"error", "blocking", "critical", "high"}
)


def _log(
    what: str, why: str, how: str, deps: RenderDeps, shot_id: str, **extra: object
) -> None:
    logger.info(
        what,
        extra={
            "who": _WHO,
            "where": f"repair_route:{shot_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            "project_id": deps.repo.project_id,
            "shot_id": shot_id,
            **extra,
        },
    )


def _load_linter() -> Callable[..., object] | None:
    try:
        module = importlib.import_module("..lint", __package__)
    except ImportError:
        return None
    fn = getattr(module, "lint_shot", None)
    return fn if callable(fn) else None


def _is_blocking(issue: object) -> bool:
    flag = getattr(issue, "blocking", None)
    if isinstance(flag, bool):
        return flag
    return str(getattr(issue, "severity", "error")).lower() in _BLOCKING_SEVERITIES


def _issue_text(issue: object) -> str:
    return str(getattr(issue, "message", None) or issue)


def lint_blocking_issues(deps: RenderDeps, shot_id: str) -> list[str]:
    """Blocking spec-linter messages for the shot; [] when the linter is unavailable."""
    lint_shot = _load_linter()
    if lint_shot is None:
        return []
    try:
        result = lint_shot(deps.repo, deps.cfg, shot_id)
    except Exception as exc:  # noqa: BLE001 - optional linter must never break repair
        _log("spec_lint_skipped", str(exc), "lint_shot raised", deps, shot_id)
        return []
    issues = getattr(result, "issues", result)
    if not isinstance(issues, Iterable) or isinstance(issues, str | bytes):
        return []
    return [_issue_text(i) for i in issues if _is_blocking(i)]


def _failed_history(
    deps: RenderDeps, shot: Shot, latest: GenerationRun
) -> list[QAReport]:
    """Failed QA reports of the shot's current content before `latest`, oldest first."""
    return [
        r.qa_scores
        for r in deps.repo.list_generation_runs(shot_id=shot.id)
        if r.id != latest.id
        and r.status == Status.FAILED
        and r.qa_scores is not None
        and run_matches_shot(r, shot)
    ]


def decide_route(deps: RenderDeps, shot: Shot, latest: GenerationRun) -> RouteDecision:
    """Spec vs render route for repairing `latest` (a failed run of the current content)."""
    report = latest.qa_scores or QAReport(passed=False)
    decision = classify_route(
        report,
        _failed_history(deps, shot, latest),
        lint_blocking_issues(deps, shot.id),
        deps.cfg.qa,
    )
    _log(
        "repair_route_decided",
        decision.why,
        f"route={decision.route} evidence={decision.evidence[:4]}",
        deps,
        shot.id,
        route=decision.route,
        run_id=latest.id,
    )
    return decision


def regenerate_spec(
    deps: RenderDeps, shot_id: str, report: QAReport, decision: RouteDecision
) -> ClipRespecResult | None:
    """Regenerate the shot's clip spec; None when the shot has no clip to regenerate."""
    feedback = list(dict.fromkeys([*spec_defect_texts(report), *decision.evidence]))
    feedback = feedback or manual_edit_reasons(report)
    try:
        return respec_clip_for_shot(deps.repo, deps.cfg, shot_id, feedback)
    except NotFound as nf:
        _log(
            "spec_regen_unavailable",
            str(nf),
            "falling back to render route",
            deps,
            shot_id,
        )
        return None

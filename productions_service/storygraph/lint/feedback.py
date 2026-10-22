"""Lint results → per-shot records (snapshot/UI) and per-scene authoring feedback (S2/S4)."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..repo import Repo
from ..schema import ShotLintIssue
from .models import LintIssue
from .remediate import AppliedFix

_log = logging.getLogger(__name__)


@dataclass
class SceneFeedback:
    """Exact linter messages for one scene, split by the stage that must fix them."""

    screenwriter: list[str] = field(default_factory=list)
    director: list[str] = field(default_factory=list)

    @property
    def needs_screenwriter(self) -> bool:
        return bool(self.screenwriter)


DEMOTED_REASON = "survived every S7 remediation round; demoted so rendering continues"


def _open_record(issue: LintIssue, demoted: bool) -> ShotLintIssue:
    if demoted and issue.severity == "error":
        return ShotLintIssue(
            code=issue.code,
            message=issue.message,
            route=issue.route,
            severity="warn",
            status="demoted",
            fix=DEMOTED_REASON,
        )
    return ShotLintIssue(
        code=issue.code,
        message=issue.message,
        route=issue.route,
        severity=issue.severity,
    )


def record_shot_lint(
    repo: Repo, issues: list[LintIssue], fixes: list[AppliedFix], demoted: bool = False
) -> int:
    """Store open issues + this run's auto-fixes on each shot; returns shots rewritten.

    With `demoted`, remaining errors are stored as `status="demoted"` warnings. S6
    records (`source="S6"`) are kept. `lint_issues` is not render content, so the content
    hash / staleness are untouched.
    """
    per_shot: dict[str, list[ShotLintIssue]] = defaultdict(list)
    for fx in fixes:
        per_shot[fx.shot_id].append(fx.record())
    for issue in issues:
        per_shot[issue.shot_id].append(_open_record(issue, demoted))
    written = 0
    for shot in repo.list_shots():
        kept = [r for r in shot.lint_issues if r.source == "S6"]
        records = [*kept, *per_shot.get(shot.id, [])]
        if records != shot.lint_issues:
            repo.put_shot(shot.model_copy(update={"lint_issues": records}))
            written += 1
    _log.info(
        "shot_lint_recorded",
        extra={
            "who": "storygraph.lint.feedback",
            "where": "record_shot_lint",
            "what": f"{len(issues)} open / {len(fixes)} auto-fixed on {written} shots",
            "when": datetime.now(UTC).isoformat(),
            "why": "expose S2/S4 lint findings per shot in the snapshot",
            "how": "Shot.lint_issues (excluded from render content hash)",
        },
    )
    return written


def scene_feedback(repo: Repo, errors: list[LintIssue]) -> dict[str, SceneFeedback]:
    """Group blocking issues by scene with clip-numbered messages for the authoring prompts."""
    out: dict[str, SceneFeedback] = defaultdict(SceneFeedback)
    for issue in errors:
        shot = repo.get_shot(issue.shot_id)
        if shot is None:
            continue
        msg = f"clip {shot.clip_index}: {issue.message}"
        fb = out[shot.scene_id]
        (fb.screenwriter if issue.route == "S2" else fb.director).append(msg)
    return dict(out)

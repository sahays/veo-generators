"""Continuity-follower re-render as a *candidate* that never costs an approved clip.

When a shot is re-rendered, later shots that chain off its last frame are re-rendered too.
A follower that already has an APPROVED clip of its current content keeps that clip as
the winner: the new render is only a candidate. On QA pass it becomes the newest APPROVED
run (assembly readiness picks it); on failure the old approved run stays the winner, the
follower is neither marked stale nor flagged, and its repair budget is untouched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final

from ..repair import ShotRepairOutcome
from ..repair.models import CandidateVerdict
from ..repo import Repo
from ..schema import GenerationRun, Shot, Status
from ..shots import run_matches_shot
from .shot_attempt import RenderDeps, next_attempt_number, render_attempt

logger = logging.getLogger(__name__)
_WHO: Final[str] = "storygraph.pipeline.continuity_candidate"


def approved_current_run(repo: Repo, shot: Shot) -> GenerationRun | None:
    """Latest APPROVED run with a stored clip rendered from the shot's current content."""
    winners = [
        r
        for r in repo.list_generation_runs(shot_id=shot.id)
        if r.status == Status.APPROVED
        and r.output_video_uri
        and run_matches_shot(r, shot)
    ]
    return max(winners, key=lambda r: r.attempt) if winners else None


def _log(what: str, why: str, deps: RenderDeps, shot_id: str, **extra: object) -> None:
    logger.info(
        what,
        extra={
            "who": _WHO,
            "where": f"continuity_candidate:{shot_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "single candidate render + critic QA against the incumbent approved run",
            "project_id": deps.repo.project_id,
            "shot_id": shot_id,
            **extra,
        },
    )


def render_follower_candidate(
    deps: RenderDeps, follower: Shot, incumbent: GenerationRun, origin: str
) -> ShotRepairOutcome:
    """Render one candidate for `follower`; replace `incumbent` only if it passes QA."""
    attempt_no = next_attempt_number(deps.repo, follower.id)
    passed = render_attempt(deps, follower, attempt_no, False)
    current = deps.repo.get_shot(follower.id) or follower
    verdict: CandidateVerdict = "accepted" if passed else "rejected"
    reasons: list[str] = []
    if passed:
        _log(
            "continuity candidate accepted",
            f"predecessor {origin} re-rendered",
            deps,
            follower.id,
            replaced_run_id=incumbent.id,
        )
    else:
        _log(
            "continuity candidate rejected",
            "candidate failed QA; old approved clip kept",
            deps,
            follower.id,
            kept_run_id=incumbent.id,
        )
        reasons = [f"continuity candidate rejected; kept approved run {incumbent.id}"]
    return ShotRepairOutcome(
        shot_id=follower.id,
        outcome="approved",
        renders=1,
        repair_attempts=current.repair_attempts,
        reasons=reasons,
        continuity_follower_of=origin,
        candidate=verdict,
    )

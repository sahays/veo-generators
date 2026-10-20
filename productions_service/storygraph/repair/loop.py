"""Repair loop for blocking shots (+ continuity followers), scene-parallel like S8.

For each target shot (blocking, not flagged `needs_manual_edit`): render once when there
is no failed clip of its current content to diagnose, then run the remaining repair
attempts (never more than `MAX_REPAIR_ATTEMPTS` per content version); flag on failure.
When a re-rendered shot becomes approved, later shots in its scene that chain off it via
`continue_from_last_frame` are re-rendered in story order. A follower that already has an
approved clip is re-rendered as a *candidate* (its old clip stays the winner unless the
candidate passes QA); other followers are marked stale and get render + QA + repairs.
Scenes run in parallel; shots within a scene run sequentially.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from ..adapters.base import VideoGenerator, VLMProvider
from ..assembly.readiness import evaluate_shot_readiness, story_ordered_shots
from ..config import Config
from ..pipeline.continuity_candidate import (
    approved_current_run,
    render_follower_candidate,
)
from ..pipeline.render_stage import group_by_scene, run_scene_groups
from ..pipeline.shot_attempt import RenderDeps, latest_current_run
from ..pipeline.shot_repair import flag_for_manual_edit, render_with_repairs
from ..repo import Repo
from ..schema import Shot
from ..shots import mark_stale_and_reset
from .models import MAX_REPAIR_ATTEMPTS, RepairReport, ShotRepairOutcome

logger = logging.getLogger(__name__)
CONTINUITY_STALE_REASON = "continuity: previous shot re-rendered"
REGENERATE_STALE_REASON = "manual regenerate requested"


def _log(what: str, why: str, how: str, project_id: str, **extra: object) -> None:
    logger.info(
        what,
        extra={
            "who": "storygraph.repair.loop",
            "where": f"repair.loop:{project_id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
            "project_id": project_id,
            **extra,
        },
    )


def _initial_renders(deps: RenderDeps, shot: Shot) -> int:
    """0 when a failed clip of the current content exists to diagnose, else 1 fresh render."""
    run = latest_current_run(deps.repo, shot)
    has_failed = (
        run is not None and run.qa_scores is not None and not run.qa_scores.passed
    )
    return 0 if has_failed and not shot.stale else 1


def _process(deps: RenderDeps, shot: Shot, initial: int | None) -> ShotRepairOutcome:
    count = _initial_renders(deps, shot) if initial is None else initial
    if shot.repair_attempts >= MAX_REPAIR_ATTEMPTS and count == 0:
        reasons = flag_for_manual_edit(deps, shot.id)
        return ShotRepairOutcome(
            shot_id=shot.id,
            outcome="flagged",
            repair_attempts=shot.repair_attempts,
            reasons=reasons,
        )
    return render_with_repairs(deps, shot.id, count)


def _followers(scene_shots: Sequence[Shot], shot_id: str) -> list[Shot]:
    """Contiguous later shots that chain off `shot_id` via `continue_from_last_frame`."""
    ordered = sorted(scene_shots, key=lambda s: s.index_in_scene)
    pos = next((i for i, s in enumerate(ordered) if s.id == shot_id), len(ordered))
    chain: list[Shot] = []
    for nxt in ordered[pos + 1 :]:
        if not nxt.continue_from_last_frame:
            break
        chain.append(nxt)
    return chain


def _rerender_follower(
    deps: RenderDeps, follower: Shot, origin: str
) -> ShotRepairOutcome:
    """Candidate render when the follower has an approved clip, else full render + repairs."""
    current = deps.repo.get_shot(follower.id) or follower
    incumbent = None if current.stale else approved_current_run(deps.repo, current)
    if incumbent is not None:
        return render_follower_candidate(deps, current, incumbent, origin)
    deps.repo.put_shot(mark_stale_and_reset(current, CONTINUITY_STALE_REASON))
    outcome = render_with_repairs(deps, follower.id, 1)
    return outcome.model_copy(update={"continuity_follower_of": origin})


def _cascade(
    deps: RenderDeps, scene_shots: Sequence[Shot], origin: str, done: set[str]
) -> list[ShotRepairOutcome]:
    """Re-render continuity followers of `origin` in order until one is not freshly approved.

    A rejected candidate keeps its old clip unchanged, so later followers (chained off
    that clip) need no re-render either.
    """
    out: list[ShotRepairOutcome] = []
    for follower in _followers(scene_shots, origin):
        outcome = _rerender_follower(deps, follower, origin)
        out.append(outcome)
        done.add(follower.id)
        if outcome.outcome != "approved" or outcome.candidate == "rejected":
            break
        origin = follower.id
    return out


def _scene_chain(
    deps: RenderDeps,
    scene_shots: Sequence[Shot],
    targets: set[str],
    initial: int | None,
) -> list[ShotRepairOutcome]:
    out: list[ShotRepairOutcome] = []
    done: set[str] = set()
    for shot in scene_shots:
        if shot.id not in targets or shot.id in done:
            continue
        current = deps.repo.get_shot(shot.id) or shot
        outcome = _process(deps, current, initial)
        out.append(outcome)
        done.add(shot.id)
        if outcome.outcome == "approved" and outcome.renders > 0:
            out.extend(_cascade(deps, scene_shots, shot.id, done))
    return out


def _run(deps: RenderDeps, targets: set[str], initial: int | None) -> RepairReport:
    groups = [
        g
        for g in group_by_scene(story_ordered_shots(deps.repo))
        if any(s.id in targets for s in g)
    ]
    parallel = deps.cfg.video.provider != "mock"
    results = run_scene_groups(
        groups, lambda g: _scene_chain(deps, g, targets, initial), parallel
    )
    report = RepairReport(outcomes=[o for grp in results for o in grp])
    _log(
        "repair_pass_completed",
        f"targets={sorted(targets)}",
        f"approved={report.approved} flagged={report.flagged}",
        deps.repo.project_id,
        total_renders=report.total_renders,
    )
    return report


def _repair_targets(repo: Repo, shot_ids: list[str] | None) -> set[str]:
    blocking = {b.shot_id for b in evaluate_shot_readiness(repo).blocking}
    wanted = blocking if shot_ids is None else blocking & set(shot_ids)
    shots = {s.id: s for s in repo.list_shots()}
    return {sid for sid in wanted if sid in shots and not shots[sid].needs_manual_edit}


def repair_failed_shots(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    shot_ids: list[str] | None = None,
) -> RepairReport:
    """Repair blocking, non-flagged shots (optionally limited to `shot_ids`)."""
    deps = RenderDeps(repo, cfg, video_gen, vlm)
    return _run(deps, _repair_targets(repo, shot_ids), None)


def regenerate_shot(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    shot_id: str,
) -> RepairReport:
    """Explicit user regenerate: fresh repair budget, render + QA + repairs, then followers."""
    shot = repo.get_shot(shot_id)
    if shot is None:
        raise KeyError(shot_id)
    repo.put_shot(mark_stale_and_reset(shot, REGENERATE_STALE_REASON))
    deps = RenderDeps(repo, cfg, video_gen, vlm)
    return _run(deps, {shot_id}, 1)

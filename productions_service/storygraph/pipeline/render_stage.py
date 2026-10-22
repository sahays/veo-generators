"""S8 render stage: compile all shots, render with QA retries + automatic repairs, scene-parallel."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TypeVar

from ..adapters.base import VideoGenerator, VLMProvider
from ..agents.critic import evaluate_clip_qa
from ..budget import select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..eval.gate import gate_fingerprint
from ..repo import Repo
from ..schema import GenerationRun, Role, Shot, Status
from ..shots import run_matches_shot
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import shot_view
from .prompt_versioning import resolve_package
from .shot_attempt import (
    RenderDeps,
    _attach_fallback,
    _collect_retry_context,
    render_attempt,
    resolve_target_resolution,
)
from .shot_repair import render_with_repairs

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_MAX_SCENE_WORKERS = 4

# Re-exported for callers/tests that import these helpers from the render stage.
_resolve_target_resolution = resolve_target_resolution
__all__ = [
    "_attach_fallback",
    "_collect_retry_context",
    "_resolve_target_resolution",
    "attempt_shot_render",
    "compile_all_shots",
    "evaluate_missing_qa",
    "render_and_qa_shots",
    "render_single_shot_with_qa",
    "run_scene_groups",
]


def compile_all_shots(
    repo: Repo, cfg: Config, video_gen: VideoGenerator
) -> dict[str, Package]:
    """Deterministically compile all shots in the repository into render packages."""
    compiled: dict[str, Package] = {}
    resolution = resolve_target_resolution(repo)
    for shot in repo.list_shots():
        sv = shot_view(repo, shot.id)
        plan = select_references(sv, cfg, caps=video_gen.caps, repo=repo)
        pkg = compile_shot(
            sv,
            plan,
            cfg,
            caps=video_gen.caps,
            project_id=repo.project_id,
            attempt=1,
            resolution=resolution,
        )
        compiled[shot.id] = resolve_package(repo, sv.shot, pkg, "compile_all").package
    return compiled


def attempt_shot_render(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
    shot: Shot,
    attempt: int,
    drop_last_frame: bool,
) -> bool:
    """Compile, generate video, and run VLM Critic QA for a single shot attempt."""
    deps = RenderDeps(repo, cfg, video_gen, vlm, compiled_packages)
    return render_attempt(deps, shot, attempt, drop_last_frame)


_SEVERE_RENDER_FLAGS: frozenset[str] = frozenset(
    {
        "style_drift",
        "frozen_frame",
        "start_frame_bleed",
        "object_materialized",
        "duplicate_prop",
        "prop_part_missing",
        "self_moving_object",
        "prop_inverted",
        "floating_object",
        "teleportation",
        "missing_character",
    }
)


def _is_shot_already_valid(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    existing_runs: list[GenerationRun],
) -> bool:
    """Return True if the shot already has a clean approved run passing critical physics & permanence QA.

    Only runs rendered from the shot's current content (`run_matches_shot`) count. The
    winning APPROVED run is judged when present, so a newer rejected continuity
    candidate never un-approves a shot that assembly readiness still accepts.
    """
    current_runs = [r for r in existing_runs if run_matches_shot(r, shot)]
    if shot.stale or not current_runs:
        return False
    winners = [
        r for r in current_runs if r.status == Status.APPROVED and r.output_video_uri
    ]
    last_run = winners[-1] if winners else current_runs[-1]
    scores = last_run.qa_scores
    if scores is not None:
        if _SEVERE_RENDER_FLAGS & set(scores.artifact_flags):
            return False
        if (
            scores.physics_plausibility < cfg.qa.physics_vlm_min
            or scores.object_permanence < cfg.qa.permanence_vlm_min
        ):
            return False
    if last_run.status == Status.APPROVED:
        return True
    if not last_run.output_video_uri or cfg.video.provider == "mock":
        return False
    return evaluate_clip_qa(repo, cfg, vlm, shot, last_run).passed


def _log_flagged_skip(repo: Repo, shot: Shot) -> None:
    logger.info(
        "Shot awaiting manual edit; S8 skips re-render",
        extra={
            "who": "storygraph.pipeline.render_stage",
            "where": "render_stage.render_single_shot_with_qa",
            "what": "flagged_shot_skipped",
            "when": datetime.now(UTC).isoformat(),
            "why": "; ".join(shot.manual_edit_reasons) or "needs_manual_edit",
            "how": "Shot.needs_manual_edit is set for the current content version",
            "project_id": repo.project_id,
            "shot_id": shot.id,
        },
    )


def render_single_shot_with_qa(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
    shot: Shot,
    max_retries: int,
) -> None:
    """Render with `max_retries` attempts, then automatic repairs; flag + file a CR if all fail.

    Shots already flagged `needs_manual_edit` are skipped until edited or regenerated.
    """
    existing_runs = repo.list_generation_runs(shot_id=shot.id)
    if _is_shot_already_valid(repo, cfg, vlm, shot, existing_runs):
        return
    if shot.needs_manual_edit:
        _log_flagged_skip(repo, shot)
        return
    deps = RenderDeps(repo, cfg, video_gen, vlm, compiled_packages)
    outcome = render_with_repairs(deps, shot.id, max_retries)
    if outcome.outcome == "flagged":
        critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
        wt.create_change_request(
            critic_ctx,
            to_role=Role.DIRECTOR,
            target_node_id=shot.id,
            reason=f"Shot '{shot.id}' failed QA after {outcome.renders} render(s) incl. repairs; needs manual edit",
            proposed_patch={"action": "manual_edit", "reasons": outcome.reasons},
        )


def run_scene_groups(
    groups: Sequence[Sequence[Shot]],
    chain: Callable[[Sequence[Shot]], _T],
    parallel: bool,
) -> list[_T]:
    """Run `chain` per scene group: sequential within a scene, bounded-parallel across scenes."""
    if not parallel or len(groups) <= 1:
        return [chain(g) for g in groups]
    with ThreadPoolExecutor(max_workers=min(_MAX_SCENE_WORKERS, len(groups))) as pool:
        return list(pool.map(chain, groups))


def group_by_scene(shots: list[Shot]) -> list[list[Shot]]:
    """Group story-ordered shots by scene, preserving story order within each group."""
    groups: dict[str, list[Shot]] = {}
    for shot in shots:
        groups.setdefault(shot.scene_id, []).append(shot)
    return list(groups.values())


def render_and_qa_shots(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
) -> None:
    """Render dirty/unrendered shots in story_order, parallelizing independent scene chains."""
    shots = sorted(
        repo.list_shots(),
        key=lambda s: (s.story_order, s.scene_id, s.index_in_scene),
    )
    max_retries = max(1, cfg.caps.shot_max_retries)

    def _chain(scene_shots: Sequence[Shot]) -> None:
        for sh in scene_shots:
            render_single_shot_with_qa(
                repo, cfg, video_gen, vlm, compiled_packages, sh, max_retries
            )

    parallel = cfg.video.provider != "mock" and len(shots) > 1
    run_scene_groups(group_by_scene(shots), _chain, parallel)


def _needs_qa(run: GenerationRun, gate_version: str) -> bool:
    """Unjudged runs, or failed runs judged under an older gate configuration."""
    qa = run.qa_scores
    if qa is None:
        return True
    stale_gate = qa.gate_version != gate_version
    return run.status == Status.FAILED and stale_gate and bool(run.output_video_uri)


def evaluate_missing_qa(repo: Repo, cfg: Config, vlm: VLMProvider) -> None:
    """S9: QA unjudged latest runs and re-judge failed ones whose gate config has changed."""
    current = gate_fingerprint(cfg)
    for shot in repo.list_shots():
        runs = repo.list_generation_runs(shot_id=shot.id)
        if runs and _needs_qa(runs[-1], current):
            logger.info(
                "S9 judging clip",
                extra={
                    "who": "storygraph.pipeline.render_stage",
                    "where": "render_stage.evaluate_missing_qa",
                    "what": "clip_qa_requalify",
                    "when": datetime.now(UTC).isoformat(),
                    "why": "unjudged or judged under an older gate",
                    "how": "evaluate_clip_qa on the latest run (no re-render)",
                    "project_id": repo.project_id,
                    "shot_id": shot.id,
                    "run_id": runs[-1].id,
                },
            )
            evaluate_clip_qa(repo, cfg, vlm, shot, runs[-1])

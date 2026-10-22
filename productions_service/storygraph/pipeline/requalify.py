"""S9 re-qualification: judge unjudged clips and re-score clips judged under an older gate.

Selection (`requalify_targets`, pure):
- the shot's latest run when it is unjudged, or FAILED under a stale gate (as before);
- every APPROVED run of the shot's *current* content whose `gate_version` is stale. A live
  critic re-score (no re-render) under the current rubric/gate replaces its verdict;
  `record_clip_qa` flips it to FAILED when it now blocks, so readiness reports the shot as
  blocking and the normal repair loop picks it up.
Shots are re-scored scene-parallel with the same bound as S8 (`run_scene_groups`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from ..adapters.base import VLMProvider
from ..agents.critic import evaluate_clip_qa
from ..config import Config
from ..eval.gate import gate_fingerprint
from ..repo import Repo
from ..schema import GenerationRun, Shot, Status
from ..shots import run_matches_shot
from .scene_parallel import group_by_scene, run_scene_groups

logger = logging.getLogger(__name__)


def needs_qa(run: GenerationRun, gate_version: str) -> bool:
    """Unjudged runs, or failed runs judged under an older gate configuration."""
    qa = run.qa_scores
    if qa is None:
        return True
    stale_gate = qa.gate_version != gate_version
    return run.status == Status.FAILED and stale_gate and bool(run.output_video_uri)


def stale_approval(run: GenerationRun, shot: Shot, gate_version: str) -> bool:
    """APPROVED clip of the shot's current content judged under an older gate."""
    qa = run.qa_scores
    return (
        run.status == Status.APPROVED
        and bool(run.output_video_uri)
        and qa is not None
        and qa.gate_version != gate_version
        and run_matches_shot(run, shot)
    )


def requalify_targets(
    shot: Shot, runs: Sequence[GenerationRun], gate_version: str
) -> list[GenerationRun]:
    """Runs of one shot S9 must (re-)judge, in run order, without duplicates."""
    picked = [r for r in runs if stale_approval(r, shot, gate_version)]
    if runs and needs_qa(runs[-1], gate_version) and runs[-1] not in picked:
        picked.append(runs[-1])
    return picked


def _log_rescore(
    repo: Repo, shot: Shot, run: GenerationRun, passed: bool, current: str
) -> None:
    was_approved = run.status == Status.APPROVED
    flipped = was_approved and not passed
    logger.info(
        "S9 clip re-judged",
        extra={
            "who": "storygraph.pipeline.requalify",
            "where": "requalify.evaluate_missing_qa",
            "what": "approval_revoked" if flipped else "clip_qa_requalified",
            "when": datetime.now(UTC).isoformat(),
            "why": (
                f"judged under gate {run.qa_scores.gate_version if run.qa_scores else None}"
                f", current {current}"
            ),
            "how": "live evaluate_clip_qa on the stored clip (no re-render)",
            "project_id": repo.project_id,
            "shot_id": shot.id,
            "run_id": run.id,
            "previous_status": run.status.value,
            "passed": passed,
        },
    )


def _requalify_shots(
    repo: Repo, cfg: Config, vlm: VLMProvider, shots: Sequence[Shot], current: str
) -> int:
    """Re-judge the targets of each shot in order; returns the number of revoked approvals."""
    revoked = 0
    for shot in shots:
        runs = repo.list_generation_runs(shot_id=shot.id)
        for run in requalify_targets(shot, runs, current):
            passed = evaluate_clip_qa(repo, cfg, vlm, shot, run).passed
            _log_rescore(repo, shot, run, passed, current)
            revoked += int(run.status == Status.APPROVED and not passed)
    return revoked


def evaluate_missing_qa(repo: Repo, cfg: Config, vlm: VLMProvider) -> int:
    """S9: judge/re-judge clips (see module doc); returns the number of revoked approvals."""
    current = gate_fingerprint(cfg)
    shots = sorted(
        repo.list_shots(), key=lambda s: (s.story_order, s.scene_id, s.index_in_scene)
    )
    parallel = cfg.video.provider != "mock" and len(shots) > 1
    counts = run_scene_groups(
        group_by_scene(shots),
        lambda g: _requalify_shots(repo, cfg, vlm, g, current),
        parallel,
    )
    return sum(counts)

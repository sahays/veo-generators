"""`S10_ASSEMBLE` stage policy: readiness + Critic ChangeRequest gate and project status mapping."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..assembly import (
    STATUS_COMPLETED,
    STATUS_COMPLETED_PARTIAL,
    assemble,
    evaluate_shot_readiness,
    select_music_mixer,
    select_normalizer,
    select_stitcher,
)
from ..config import Config
from ..errors import ShotsNotApproved
from ..repo import Repo
from ..schema import ChangeRequest, Role
from .post_render.dispatch import apply_audio_post, stem_renderer_for

logger = logging.getLogger(__name__)

STATUS_NEEDS_REVIEW = "needs_review"
_TERMINAL_SUCCESS = frozenset({STATUS_COMPLETED, STATUS_COMPLETED_PARTIAL})


def open_critic_change_requests(repo: Repo) -> list[ChangeRequest]:
    """Return open ChangeRequests filed by the Critic (e.g. shots that exhausted QA retries)."""
    return [
        cr
        for cr in repo.list_change_requests(open_only=True)
        if cr.from_role == Role.CRITIC
    ]


def _strict_blockers(repo: Repo) -> dict[str, list[str]]:
    """Merge unapproved shots and open Critic ChangeRequests into one blocking map."""
    blocked = evaluate_shot_readiness(repo).blocking_reasons()
    for cr in open_critic_change_requests(repo):
        blocked.setdefault(cr.target_node_id, []).append(
            f"open critic CR {cr.id}: {cr.reason}"
        )
    return blocked


def run_assemble_stage(repo: Repo, cfg: Config, allow_partial: bool = False) -> str:
    """Gate and execute S10; strict mode raises `ShotsNotApproved` before any stitching."""
    if not allow_partial:
        blocked = _strict_blockers(repo)
        if blocked:
            logger.warning(
                "S10 assembly gated: unapproved shots or open Critic ChangeRequests",
                extra={
                    "who": "storygraph.pipeline",
                    "where": "pipeline.assemble_stage",
                    "what": "assembly_gate_blocked",
                    "when": datetime.now(UTC).isoformat(),
                    "why": "shots not APPROVED or Critic CRs open",
                    "how": "evaluate_shot_readiness + list_change_requests",
                    "blocking_ids": list(blocked),
                },
            )
            raise ShotsNotApproved(blocked, context="S10_ASSEMBLE")
    apply_audio_post(repo, cfg)  # audio.mode: omni (no-op) | voiceover_duck | stems
    return assemble(
        repo,
        allow_partial=allow_partial,
        stitcher=select_stitcher(cfg.video.provider),
        music_mixer=select_music_mixer(cfg.video.provider),
        assembly_cfg=cfg.assembly,
        normalizer=select_normalizer(cfg.video.provider),
        prefer_voiced=cfg.audio.mode == "voiceover_duck",
        stem_render=stem_renderer_for(repo, cfg),
    )


def project_status_after_stage(
    is_assemble: bool, current_status: str, error: str | None, needs_review: bool
) -> str:
    """Map a stage outcome to `ProjectMeta.status`."""
    if error is not None:
        return STATUS_NEEDS_REVIEW if needs_review else "failed"
    if not is_assemble:
        return "running"
    return current_status if current_status in _TERMINAL_SUCCESS else STATUS_COMPLETED

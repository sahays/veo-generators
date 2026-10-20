"""Pure shot-readiness evaluation for final assembly (`S10_ASSEMBLE`).

A shot is *ready* only when it is not stale and has an APPROVED `GenerationRun` with a
stored video that was rendered from the shot's current content (`content_hash`).
Every other shot is *blocking*; failed or outdated clips are never used as fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from ..repo import Repo
from ..schema import GenerationRun, Shot, Status

NOT_RENDERED_STATUS = "not_rendered"
OUTDATED_STATUS = "outdated"
OUTDATED_REASON = (
    "approved clip is from an older screenplay/shot version; re-render required"
)


class ReadyShot(BaseModel):
    """The winning APPROVED clip for a shot."""

    shot_id: str
    run_id: str
    video_uri: str


class BlockingShot(BaseModel):
    """A shot that has no APPROVED clip, with the latest attempt's QA verdict."""

    shot_id: str
    latest_status: str
    failure_reasons: list[str] = Field(default_factory=list)
    artifact_flags: list[str] = Field(default_factory=list)


class AssemblyReadiness(BaseModel):
    """Per-shot assembly readiness, both lists in story order."""

    ready_shots: list[ReadyShot] = Field(default_factory=list)
    blocking: list[BlockingShot] = Field(default_factory=list)
    is_complete: bool = False

    def blocking_reasons(self) -> dict[str, list[str]]:
        """Map each blocking shot id to readable reasons (for `ShotsNotApproved`)."""
        return {
            b.shot_id: [
                f"latest={b.latest_status}",
                *b.failure_reasons,
                *b.artifact_flags,
            ]
            for b in self.blocking
        }


def story_ordered_shots(repo: Repo) -> list[Shot]:
    """Return all shots sorted by (story_order, scene_id, index_in_scene)."""
    return sorted(
        repo.list_shots(), key=lambda s: (s.story_order, s.scene_id, s.index_in_scene)
    )


def _is_newer(candidate: GenerationRun, current: GenerationRun | None) -> bool:
    return current is None or candidate.attempt >= current.attempt


@dataclass
class _RunIndex:
    """Per-shot run lookups restricted to runs rendered from the shot's current content."""

    latest: dict[str, GenerationRun] = field(default_factory=dict)
    winners: dict[str, GenerationRun] = field(default_factory=dict)
    outdated_approved: set[str] = field(default_factory=set)


def _index_runs(
    runs: list[GenerationRun], shot_hashes: dict[str, str | None]
) -> _RunIndex:
    """Single O(N) pass: latest/winning runs of current content, plus shots with outdated approvals.

    A run counts only if its `shot_content_hash` equals the shot's `content_hash`
    (legacy runs with no hash count only for legacy shots with no hash).
    """
    idx = _RunIndex()
    for run in runs:
        if run.shot_id not in shot_hashes:
            continue
        is_winner = run.status == Status.APPROVED and bool(run.output_video_uri)
        if run.shot_content_hash != shot_hashes[run.shot_id]:
            if is_winner:
                idx.outdated_approved.add(run.shot_id)
            continue
        if _is_newer(run, idx.latest.get(run.shot_id)):
            idx.latest[run.shot_id] = run
        if is_winner and _is_newer(run, idx.winners.get(run.shot_id)):
            idx.winners[run.shot_id] = run
    return idx


def _stale_reasons(shot: Shot) -> list[str]:
    if not shot.stale:
        return []
    return [f"shot is stale: {shot.stale_reason or 'upstream content changed'}"]


def _blocking_for(shot: Shot, idx: _RunIndex) -> BlockingShot:
    latest = idx.latest.get(shot.id)
    stale = _stale_reasons(shot)
    if latest is not None:
        qa = latest.qa_scores
        return BlockingShot(
            shot_id=shot.id,
            latest_status=str(latest.status),
            failure_reasons=[*stale, *(qa.failure_reasons if qa else [])],
            artifact_flags=list(qa.artifact_flags) if qa else [],
        )
    if shot.id in idx.outdated_approved:
        return BlockingShot(
            shot_id=shot.id,
            latest_status=OUTDATED_STATUS,
            failure_reasons=[*stale, OUTDATED_REASON],
        )
    return BlockingShot(
        shot_id=shot.id,
        latest_status=NOT_RENDERED_STATUS,
        failure_reasons=[*stale, "no generation run exists for this shot"],
    )


def evaluate_shot_readiness(repo: Repo) -> AssemblyReadiness:
    """Classify every shot as ready (current-content APPROVED clip, not stale) or blocking."""
    shots = story_ordered_shots(repo)
    idx = _index_runs(
        repo.list_generation_runs(), {s.id: s.content_hash for s in shots}
    )
    ready: list[ReadyShot] = []
    blocking: list[BlockingShot] = []
    for shot in shots:
        win = idx.winners.get(shot.id)
        if win is not None and win.output_video_uri and not shot.stale:
            ready.append(
                ReadyShot(
                    shot_id=shot.id, run_id=win.id, video_uri=win.output_video_uri
                )
            )
        else:
            blocking.append(_blocking_for(shot, idx))
    return AssemblyReadiness(
        ready_shots=ready,
        blocking=blocking,
        is_complete=bool(ready) and not blocking,
    )

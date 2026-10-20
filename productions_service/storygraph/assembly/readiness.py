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
    # Repair / manual-edit context so the UI can render an editor without extra calls.
    scene_id: str = ""
    clip_index: int | None = None
    clip_omni_prompt: str | None = None
    needs_manual_edit: bool = False
    repair_attempts: int = 0
    manual_edit_reasons: list[str] = Field(default_factory=list)


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


def _verdict(shot: Shot, idx: _RunIndex) -> tuple[str, list[str], list[str]]:
    """(latest_status, failure_reasons, artifact_flags) for a blocking shot."""
    latest = idx.latest.get(shot.id)
    stale = _stale_reasons(shot)
    if latest is not None:
        qa = latest.qa_scores
        reasons = [*stale, *(qa.failure_reasons if qa else [])]
        return str(latest.status), reasons, list(qa.artifact_flags) if qa else []
    if shot.id in idx.outdated_approved:
        return OUTDATED_STATUS, [*stale, OUTDATED_REASON], []
    missing = "no generation run exists for this shot"
    return NOT_RENDERED_STATUS, [*stale, missing], []


def _blocking_for(shot: Shot, idx: _RunIndex, clip_prompt: str | None) -> BlockingShot:
    status, reasons, flags = _verdict(shot, idx)
    return BlockingShot(
        shot_id=shot.id,
        latest_status=status,
        failure_reasons=reasons,
        artifact_flags=flags,
        scene_id=shot.scene_id,
        clip_index=shot.clip_index,
        clip_omni_prompt=clip_prompt,
        needs_manual_edit=shot.needs_manual_edit,
        repair_attempts=shot.repair_attempts,
        manual_edit_reasons=list(shot.manual_edit_reasons),
    )


def _clip_prompts(repo: Repo) -> dict[tuple[str, int], str]:
    """(scene_id, clip_index) -> omni_prompt for every scene clip, in one pass."""
    return {
        (sc.id, c.clip_index): c.omni_prompt
        for sc in repo.list_scenes()
        for c in sc.clips
    }


def evaluate_shot_readiness(repo: Repo) -> AssemblyReadiness:
    """Classify every shot as ready (current-content APPROVED clip, not stale) or blocking."""
    shots = story_ordered_shots(repo)
    idx = _index_runs(
        repo.list_generation_runs(), {s.id: s.content_hash for s in shots}
    )
    ready: list[ReadyShot] = []
    blocking: list[BlockingShot] = []
    prompts: dict[tuple[str, int], str] | None = None
    for shot in shots:
        win = idx.winners.get(shot.id)
        if win is not None and win.output_video_uri and not shot.stale:
            ready.append(
                ReadyShot(
                    shot_id=shot.id, run_id=win.id, video_uri=win.output_video_uri
                )
            )
        else:
            prompts = _clip_prompts(repo) if prompts is None else prompts
            key = (
                (shot.scene_id, shot.clip_index)
                if shot.clip_index is not None
                else None
            )
            blocking.append(_blocking_for(shot, idx, prompts.get(key) if key else None))
    return AssemblyReadiness(
        ready_shots=ready,
        blocking=blocking,
        is_complete=bool(ready) and not blocking,
    )

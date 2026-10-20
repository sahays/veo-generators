"""Story-level Stage QA: duplicate beats and time-of-day regressions as `StageQaIssue`s.

S1 codes (events, scene outlines, time of day) route to STORY_ARCHITECT; S2 codes (clips,
dialogue lines) route to SCREENWRITER via `stages_to_redo_for_issues` prefix mapping.
`story_guard_block` turns the same findings into prompt feedback for the next draft.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final

from ..repo import Repo
from ..schema import StageQaIssue
from .beats import BeatKind, collect_script_beats, collect_story_beats
from .dedup import DuplicateBeat, find_duplicate_beats
from .timeline import find_time_regressions

logger = logging.getLogger(__name__)

STAGE_S1: Final[str] = "S1_EXTRACT"
_CODE_BY_KIND: Final[dict[BeatKind, str]] = {
    BeatKind.EVENT: "S1_DUPLICATE_EVENT",
    BeatKind.SCENE: "S1_DUPLICATE_SCENE",
    BeatKind.CLIP: "S2_DUPLICATE_CLIP_BEAT",
    BeatKind.LINE: "S2_DUPLICATE_LINE",
}
_TOD_CODE: Final[str] = "S1_TIME_OF_DAY_REGRESSION"
_MAX_GUARD_ITEMS: Final[int] = 25


def _dup_issue(dup: DuplicateBeat) -> StageQaIssue:
    kind = dup.repeat.kind
    return StageQaIssue(
        code=_CODE_BY_KIND[kind],
        node_id=dup.repeat.node_id,
        dimension="story",
        message=(
            f"{kind.value} {dup.repeat.node_id} ({dup.repeat.scene_id}) repeats "
            f"{dup.original.node_id} ({dup.original.scene_id}) at similarity "
            f"{dup.similarity}: '{dup.repeat.text[:120]}'"
        ),
        remediation=(
            "Each scene must advance the story: replace the repeated gag/action/line "
            "with a new beat, or mark it an explicit callback."
        ),
    )


def _time_issues(repo: Repo) -> list[StageQaIssue]:
    return [
        StageQaIssue(
            code=_TOD_CODE,
            node_id=r.scene_id,
            dimension="continuity",
            message=(
                f"{r.scene_id} time_of_day '{r.time_of_day}' regresses from "
                f"'{r.previous_time_of_day}' in continuous scene {r.previous_scene_id}"
            ),
            remediation="Keep time_of_day monotonic within continuous scenes.",
        )
        for r in find_time_regressions(repo.list_scenes())
    ]


def detect_story_issues(repo: Repo, stage: str) -> list[StageQaIssue]:
    """S1 story issues always; S2 script issues for any stage after S1_EXTRACT."""
    beats = collect_story_beats(repo)
    if stage != STAGE_S1:
        beats += collect_script_beats(repo)
    issues = [_dup_issue(d) for d in find_duplicate_beats(beats)]
    return issues + _time_issues(repo)


def _scene_dup_issues(repo: Repo, scene_id: str) -> list[StageQaIssue]:
    """S2 duplicate-beat issues where `scene_id` holds the original or the repeat."""
    beats = collect_story_beats(repo) + collect_script_beats(repo)
    return [
        _dup_issue(d)
        for d in find_duplicate_beats(beats)
        if scene_id in (d.repeat.scene_id, d.original.scene_id)
    ]


def _guard_lines(issues: list[StageQaIssue]) -> list[str]:
    return [f"- {i.message}" for i in issues[:_MAX_GUARD_ITEMS]]


def architect_guard_block(repo: Repo) -> str:
    """Prompt feedback listing the current draft's S1 story defects ('' when clean)."""
    lines = _guard_lines(detect_story_issues(repo, STAGE_S1))
    if not lines:
        return ""
    return "PREVIOUS DRAFT STORY DEFECTS (fix every one):\n" + "\n".join(lines) + "\n"


def screenwriter_guard_block(repo: Repo, scene_id: str) -> str:
    """Prompt feedback: lines/beats already used in other scenes plus this scene's repeats."""
    others = {s.id for s in repo.list_scenes() if s.id != scene_id}
    used = [
        f"- {b.scene_id}: {b.text[:100]}"
        for b in collect_script_beats(repo, others)
        if b.kind == BeatKind.LINE and not b.callback
    ][:_MAX_GUARD_ITEMS]
    repeats = _scene_dup_issues(repo, scene_id)
    block = ""
    if used:
        block += (
            "LINES ALREADY SPOKEN IN OTHER SCENES (do not reuse):\n"
            + "\n".join(used)
            + "\n"
        )
    if repeats:
        block += (
            "PREVIOUS DRAFT REPEATS (replace them):\n"
            + "\n".join(_guard_lines(repeats))
            + "\n"
        )
    return block


def log_scene_duplicates(repo: Repo, scene_id: str, who: str) -> list[StageQaIssue]:
    """Post-authoring hook: log duplicate beats touching `scene_id` and return them."""
    found = _scene_dup_issues(repo, scene_id)
    if found:
        logger.warning(
            "Duplicate story beats detected after authoring",
            extra={
                "who": who,
                "where": "storygraph.story.qa",
                "what": "duplicate_beats_detected",
                "when": datetime.now(UTC).isoformat(),
                "why": "scene repeats a gag, action, or line from another scene",
                "how": "minhash/LSH over verb+object+dialogue tokens",
                "scene_id": scene_id,
                "issue_codes": sorted({i.code for i in found}),
                "node_ids": [i.node_id for i in found],
            },
        )
    return found

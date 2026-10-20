"""Manual clip edit for a flagged shot: patch its scene `ClipScript`, validate, invalidate.

Edits touch only the clip's `omni_prompt` and/or the action text of interaction steps the
clip covers. The edited scene is re-validated with the screenplay clip and species rules;
only issues *introduced* by the edit are rejected (pre-existing ones never block an edit).
On success the shot gets a fresh content hash, is marked stale and its repair budget reset.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final

from pydantic import BaseModel, Field

from ..clips.graph_checks import collect_clip_issues
from ..clips.models import ClipScript
from ..clips.validation import ClipIssue
from ..errors import NotFound, ValidationFailed
from ..repo import Repo
from ..schema import Scene, Shot
from ..shots import compute_shot_content_hash, find_scene_clip, mark_stale_and_reset

logger = logging.getLogger(__name__)
MAX_EDIT_CHARS: Final[int] = 2000
EDIT_STALE_REASON: Final[str] = "clip edited manually"
CODE_EDIT_STEP: Final[str] = "S2_CLIP_EDIT_STEP"
CODE_EDIT_EMPTY: Final[str] = "S2_CLIP_EDIT_EMPTY"


class ClipEdit(BaseModel):
    """User edit of one shot's clip (all fields optional; at least one required)."""

    omni_prompt: str | None = Field(default=None, max_length=MAX_EDIT_CHARS)
    step_actions: dict[int, str] | None = None


def _step_issues(scene: Scene, clip: ClipScript, edit: ClipEdit) -> list[ClipIssue]:
    issues: list[ClipIssue] = []
    if edit.omni_prompt is None and not edit.step_actions:
        issues.append(ClipIssue(CODE_EDIT_EMPTY, scene.id, "Nothing to edit."))
    for idx, action in (edit.step_actions or {}).items():
        if idx not in clip.step_indices:
            msg = f"Step {idx} is not part of clip {clip.clip_index} (steps {clip.step_indices})."
            issues.append(ClipIssue(CODE_EDIT_STEP, scene.id, msg))
        elif not action.strip() or len(action) > MAX_EDIT_CHARS:
            msg = f"Step {idx} action must be 1-{MAX_EDIT_CHARS} characters."
            issues.append(ClipIssue(CODE_EDIT_STEP, scene.id, msg))
    return issues


def _apply(scene: Scene, clip: ClipScript, edit: ClipEdit) -> tuple[Scene, ClipScript]:
    new_clip = clip
    if edit.omni_prompt is not None:
        new_clip = clip.model_copy(update={"omni_prompt": edit.omni_prompt.strip()})
    actions = {k: v.strip() for k, v in (edit.step_actions or {}).items()}
    steps = [
        s.model_copy(update={"action": actions[s.step_index]})
        if s.step_index in actions
        else s
        for s in scene.interaction_steps
    ]
    clips = [new_clip if c.clip_index == clip.clip_index else c for c in scene.clips]
    return scene.model_copy(
        update={"clips": clips, "interaction_steps": steps}
    ), new_clip


def _issues(repo: Repo, scene: Scene) -> list[ClipIssue]:
    return collect_clip_issues(
        [scene],
        repo.list_dialogue(scene_id=scene.id),
        [],
        False,
        entities=repo.list_entities(),
        appearances=repo.list_appearances(),
    )


def _introduced(repo: Repo, before: Scene, after: Scene) -> list[ClipIssue]:
    seen = {(i.code, i.message) for i in _issues(repo, before)}
    return [i for i in _issues(repo, after) if (i.code, i.message) not in seen]


def load_shot_clip(repo: Repo, shot_id: str) -> tuple[Shot, Scene, ClipScript]:
    """(shot, its scene, its 1:1 scene clip); raises `NotFound` if any is missing."""
    shot = repo.get_shot(shot_id)
    scene = repo.get_scene(shot.scene_id) if shot else None
    clip = find_scene_clip(scene.clips, shot.clip_index) if shot and scene else None
    if shot is None or scene is None or clip is None:
        raise NotFound(f"Shot '{shot_id}' or its scene clip was not found")
    return shot, scene, clip


def apply_clip_edit(
    repo: Repo, scene: Scene, clip: ClipScript, edit: ClipEdit
) -> ClipScript:
    """Validate `edit` against the screenplay clip rules and persist it on the scene.

    Raises `ValidationFailed` for malformed edits or issues the edit would introduce.
    """
    pre = _step_issues(scene, clip, edit)
    if pre:
        raise ValidationFailed(pre)
    new_scene, new_clip = _apply(scene, clip, edit)
    introduced = _introduced(repo, scene, new_scene)
    if introduced:
        raise ValidationFailed(introduced)
    repo.put_scene(new_scene)
    return new_clip


def edit_shot_clip(repo: Repo, shot_id: str, edit: ClipEdit) -> Shot:
    """Validate + persist the clip edit; return the shot (stale, repair state reset)."""
    shot, scene, clip = load_shot_clip(repo, shot_id)
    new_clip = apply_clip_edit(repo, scene, clip, edit)
    hashed = shot.model_copy(
        update={"content_hash": compute_shot_content_hash(shot, new_clip)}
    )
    saved = repo.put_shot(mark_stale_and_reset(hashed, EDIT_STALE_REASON))
    logger.info(
        "Shot clip edited manually; shot invalidated for re-render",
        extra={
            "who": "studio_user",
            "where": "storygraph.repair.clip_edit.edit_shot_clip",
            "what": "shot_clip_edited",
            "when": datetime.now(UTC).isoformat(),
            "why": "; ".join(shot.manual_edit_reasons) or "user edit",
            "how": f"omni_prompt={edit.omni_prompt is not None} steps={sorted(edit.step_actions or {})}",
            "project_id": repo.project_id,
            "shot_id": shot_id,
            "prev_hash": shot.content_hash,
            "new_hash": saved.content_hash,
        },
    )
    return saved

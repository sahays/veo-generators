"""Validation policy: which issues may block rendering, which are fixed, which are demoted.

Only truly unrenderable shots block (the video model has nothing coherent to render):
* `U_NO_LOCATION` – the shot has no location, or its location entity does not exist;
* `U_NO_CAST`     – the shot's clip has character actions but the shot casts nobody;
* `U_EMPTY_SPEC`  – no clip, no beats, no events and no dialogue: nothing to show.
Every other validation / lint issue is remediated deterministically where possible and
otherwise demoted to a per-shot warning (`validation.demotion`).
"""

from __future__ import annotations

from typing import Final

from ..repo import Repo
from ..schema import EntityType, Scene, Shot
from ..validate import ValidationIssue

UNRENDERABLE: Final[frozenset[str]] = frozenset(
    {"U_NO_LOCATION", "U_NO_CAST", "U_EMPTY_SPEC"}
)


def _clip_actors(scene: Scene | None, shot: Shot) -> set[str]:
    if scene is None or shot.clip_index is None:
        return set()
    clip = next((c for c in scene.clips if c.clip_index == shot.clip_index), None)
    wanted = set(clip.step_indices) if clip else set()
    return {s.actor_id for s in scene.interaction_steps if s.step_index in wanted}


def _has_content(scene: Scene | None, shot: Shot) -> bool:
    has_clip = scene is not None and any(
        c.clip_index == shot.clip_index and (c.step_indices or c.omni_prompt.strip())
        for c in scene.clips
    )
    return bool(has_clip or shot.beats or shot.covers_event_ids or shot.dialogue_ids)


def _shot_issues(
    shot: Shot, scene: Scene | None, locations: set[str], chars: set[str]
) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    if not shot.location_id or shot.location_id not in locations:
        msg = f"Shot '{shot.id}' is unrenderable: location '{shot.location_id or '-'}' is missing"
        out.append(ValidationIssue("U_NO_LOCATION", "error", shot.id, msg))
    if not shot.cast and _clip_actors(scene, shot) & chars:
        msg = f"Shot '{shot.id}' is unrenderable: its clip has character actions but no cast"
        out.append(ValidationIssue("U_NO_CAST", "error", shot.id, msg))
    if not _has_content(scene, shot):
        msg = f"Shot '{shot.id}' is unrenderable: empty spec (no clip, beats, events or dialogue)"
        out.append(ValidationIssue("U_EMPTY_SPEC", "error", shot.id, msg))
    return out


def unrenderable_issues(repo: Repo) -> list[ValidationIssue]:
    """Blocking renderability issues for every shot, in O(shots + scenes + entities)."""
    ents = repo.list_entities()
    locations = {e.id for e in ents if e.entity_type == EntityType.LOCATION}
    chars = {e.id for e in ents if e.entity_type == EntityType.CHARACTER}
    scenes = {s.id: s for s in repo.list_scenes()}
    return [
        issue
        for shot in repo.list_shots()
        for issue in _shot_issues(shot, scenes.get(shot.scene_id), locations, chars)
    ]

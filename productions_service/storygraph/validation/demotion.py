"""Demote surviving non-blocking validation issues to per-shot warnings (no dead ends).

Each issue is attached to the shots it affects so the snapshot / UI shows exactly where
and why: a shot id maps to itself; a scene id maps to the clip / step its message names
("Clip 2", "Step 3") or else to every shot of the scene; an entity id maps to shots that
cast or carry it; an event id maps to shots that play it. Records are stored on
`Shot.lint_issues` with `source="S6"`, `status="demoted"`, `severity="warn"`.
"""

from __future__ import annotations

import re
from typing import Final

from ..repo import Repo
from ..schema import Scene, Shot, ShotLintIssue
from ..validate import ValidationIssue

_CLIP_RE: Final[re.Pattern[str]] = re.compile(r"\bClip (\d+)\b")
_STEP_RE: Final[re.Pattern[str]] = re.compile(r"\bStep (\d+)\b")


def _scene_targets(scene: Scene, shots: list[Shot], message: str) -> list[Shot]:
    clip_m, step_m = _CLIP_RE.search(message), _STEP_RE.search(message)
    clip_idx = int(clip_m.group(1)) if clip_m else None
    if clip_idx is None and step_m:
        step = int(step_m.group(1))
        clip_idx = next(
            (c.clip_index for c in scene.clips if step in c.step_indices), None
        )
    picked = [s for s in shots if clip_idx is not None and s.clip_index == clip_idx]
    return picked or shots


def affected_shots(
    issue: ValidationIssue, shots: list[Shot], scenes: dict[str, Scene]
) -> list[Shot]:
    """Shots an issue should be attached to (possibly none for graph-level issues)."""
    nid = issue.node_id
    direct = [s for s in shots if s.id == nid]
    if direct:
        return direct
    if nid in scenes:
        in_scene = [s for s in shots if s.scene_id == nid]
        return _scene_targets(scenes[nid], in_scene, issue.message)
    return [
        s
        for s in shots
        if nid in s.prop_ids
        or nid in s.covers_event_ids
        or any(c.entity_id == nid for c in s.cast)
    ]


def _record(issue: ValidationIssue, reason: str) -> ShotLintIssue:
    return ShotLintIssue(
        code=issue.code,
        message=issue.message,
        route="S2" if issue.code.startswith("S2") else "S4",
        severity="warn",
        status="demoted",
        fix=reason,
        source="S6",
    )


def demote_to_shots(repo: Repo, issues: list[ValidationIssue], reason: str) -> int:
    """Replace each shot's S6 records with the demoted `issues`; returns shots rewritten."""
    shots = repo.list_shots()
    scenes = {s.id: s for s in repo.list_scenes()}
    per_shot: dict[str, list[ShotLintIssue]] = {}
    for issue in issues:
        for shot in affected_shots(issue, shots, scenes):
            per_shot.setdefault(shot.id, []).append(_record(issue, reason))
    written = 0
    for shot in shots:
        others = [r for r in shot.lint_issues if r.source != "S6"]
        records = [*per_shot.get(shot.id, []), *others]
        if records != shot.lint_issues:
            repo.put_shot(shot.model_copy(update={"lint_issues": records}))
            written += 1
    return written

"""Deterministic S7 remediation of blocking spec-lint issues (runs before any LLM redo).

* `S4_LINT_CAMERA_MOVEMENT` → the shot camera is adjusted to follow the locomotion
  (track, or pan for a lateral crossing; size widened per `LocomotionCameraPolicy`; angle and
  lens kept). Never blocks.
* `S2_CLIP_LINT_TOO_MANY_ACTIONS` → the clip is split into contiguous clips (`split_clip`).
* `S2_CLIP_LINT_TOO_MANY_WORDS` → overflow lines move to an adjacent clip when they fit.

Clip edits only touch `Scene.clips`; the caller re-maps the scene's shots through the
director (`RemediationResult.remap`) so content hashes / staleness follow the normal path.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from ..audit import append_audit
from ..clips.limits import LOCOMOTION_CAMERA, widen_to
from ..clips.models import ClipScript
from ..clips.rebalance import ClipEdit, move_overflow_lines, split_clip
from ..clips.refs import dialogue_refs, entity_names, step_refs
from ..clips.text import DialogueRef, StepRef
from ..repo import Repo
from ..schema import CameraSpec, Role, Scene, Shot, ShotLintIssue
from ..shots.stamp import stamp_content_hash
from ..timeline.clip_context import clip_steps_of
from ..timeline.locomotion import LocomotionHit, step_locomotion
from .models import CODE_CAMERA, CODE_TOO_MANY_ACTIONS, CODE_TOO_MANY_WORDS, LintIssue

_log = logging.getLogger(__name__)
_WHO = "storygraph.lint.remediate"
ClipEditFn = Callable[
    [list[ClipScript], int, dict[int, StepRef], dict[str, DialogueRef]],
    ClipEdit | None,
]
_CLIP_EDITS: dict[str, ClipEditFn] = {
    CODE_TOO_MANY_ACTIONS: split_clip,
    CODE_TOO_MANY_WORDS: move_overflow_lines,
}


@dataclass(frozen=True)
class AppliedFix:
    """One deterministic fix, attached to its shot as an `auto_fixed` lint record."""

    shot_id: str
    issue: LintIssue
    fix: str
    scene_id: str = ""  # set for clip edits: the shot is re-resolved after re-mapping
    clip_index: int | None = None

    def record(self) -> ShotLintIssue:
        i = self.issue
        return ShotLintIssue(
            code=i.code,
            message=i.message,
            route=i.route,
            status="auto_fixed",
            fix=self.fix,
        )


@dataclass
class RemediationResult:
    """Fixes applied, scenes whose clips changed (new clip → origin clip) and leftovers."""

    fixes: list[AppliedFix] = field(default_factory=list)
    remap: dict[str, dict[int, int | None]] = field(default_factory=dict)
    residual: list[LintIssue] = field(default_factory=list)


def _log_fix(what: str, target: str, why: str, how: str) -> None:
    _log.info(
        "lint_remediation_applied",
        extra={
            "who": _WHO,
            "where": target,
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
        },
    )


def plan_camera_fix(
    cam: CameraSpec, hit: LocomotionHit, exit_vector: str
) -> CameraSpec:
    """Camera that follows `hit`: pan for a lateral crossing, else track; widened; angle/lens kept."""
    pol = LOCOMOTION_CAMERA
    if hit.lateral:
        leftward = "left" in f"{exit_vector} {hit.clause}".lower()
        move, floor = ("pan_l" if leftward else "pan_r"), pol.pan_min_size
    else:
        move, floor = "track", pol.track_min_size
    return cam.model_copy(
        update={"movement": move, "shot_size": widen_to(cam.shot_size, floor)}
    )


def _clip_of(scene: Scene, shot: Shot) -> ClipScript | None:
    return next((c for c in scene.clips if c.clip_index == shot.clip_index), None)


def _fix_camera(repo: Repo, issue: LintIssue) -> AppliedFix | None:
    shot = repo.get_shot(issue.shot_id)
    scene = repo.get_scene(shot.scene_id) if shot else None
    clip = _clip_of(scene, shot) if scene and shot else None
    if shot is None or scene is None or clip is None:
        return None
    steps = clip_steps_of(scene, clip)
    hit = next((h for s in steps if (h := step_locomotion(s))), None)
    if hit is None:
        return None
    old = shot.camera
    cam = plan_camera_fix(old, hit, shot.exit_motion_vector)
    fix = f"camera {old.shot_size}/{old.movement} -> {cam.shot_size}/{cam.movement}"
    updated = shot.model_copy(update={"camera": cam})
    repo.put_shot(stamp_content_hash(repo, shot, updated, _WHO))
    _log_fix("camera_adjusted", shot.id, issue.message, fix)
    return AppliedFix(shot.id, issue, fix)


def fix_cameras(repo: Repo, issues: list[LintIssue]) -> RemediationResult:
    """Adjust every shot camera that cannot follow its clip's locomotion."""
    out = RemediationResult()
    for issue in issues:
        applied = _fix_camera(repo, issue) if issue.code == CODE_CAMERA else None
        if applied is None:
            out.residual.append(issue)
        else:
            out.fixes.append(applied)
    return out


def _scene_refs(
    repo: Repo, scene: Scene
) -> tuple[dict[int, StepRef], dict[str, DialogueRef]]:
    names = entity_names(repo.list_entities())
    steps = {s.step_index: s for s in step_refs(scene.interaction_steps, names)}
    lines = dialogue_refs(repo.list_dialogue(scene_id=scene.id), names)
    return steps, {ln.line_id: ln for ln in lines}


def _compose(
    origin: dict[int, int | None], step: dict[int, int | None]
) -> dict[int, int | None]:
    """Chain origin maps: new clip → previous clip → original clip."""
    return {n: (origin.get(o) if o is not None else None) for n, o in step.items()}


def _edit_scene(
    repo: Repo, scene: Scene, items: list[tuple[int, LintIssue]], out: RemediationResult
) -> None:
    """Apply clip edits right-to-left (indices of unprocessed clips never shift)."""
    steps, lines = _scene_refs(repo, scene)
    clips = list(scene.clips)
    origin: dict[int, int | None] = {c.clip_index: c.clip_index for c in clips}
    by_index = {c.clip_index: c for c in clips}
    for clip_index, issue in sorted(items, key=lambda t: -t[0]):
        fn = _CLIP_EDITS[issue.code]
        edit = fn(clips, clip_index, steps, lines) if clip_index in by_index else None
        if edit is None:
            out.residual.append(issue)
            continue
        clips, origin = edit.clips, _compose(origin, edit.origin)
        out.fixes.append(
            AppliedFix(issue.shot_id, issue, edit.note, scene.id, clip_index)
        )
        _log_fix("clip_edited", scene.id, issue.message, edit.note)
    if clips != scene.clips:
        saved = repo.put_scene(scene.model_copy(update={"clips": clips}))
        note = f"S7 lint remediation: {len(clips)} clips"
        append_audit(
            repo.store, Role.PIPELINE, "lint_remediate_clips", scene.id,
            scene.version, saved.version, note,
        )  # fmt: skip
        out.remap[scene.id] = origin


def fix_clip_load(repo: Repo, issues: list[LintIssue]) -> RemediationResult:
    """Split overloaded clips / move overflow dialogue; other issues pass through."""
    out = RemediationResult()
    per_scene: dict[str, list[tuple[int, LintIssue]]] = defaultdict(list)
    for issue in issues:
        shot = repo.get_shot(issue.shot_id) if issue.code in _CLIP_EDITS else None
        if shot is None or shot.clip_index is None:
            out.residual.append(issue)
            continue
        per_scene[shot.scene_id].append((shot.clip_index, issue))
    for scene_id, items in per_scene.items():
        scene = repo.get_scene(scene_id)
        if scene is None:
            out.residual.extend(i for _, i in items)
            continue
        _edit_scene(repo, scene, items, out)
    return out


def rekey_fixes(repo: Repo, fixes: list[AppliedFix]) -> list[AppliedFix]:
    """Point clip-edit fixes at the shot now rendering their clip (ids change on re-map)."""
    out: list[AppliedFix] = []
    for fx in fixes:
        shots = repo.list_shots(scene_id=fx.scene_id) if fx.scene_id else []
        sid = next((s.id for s in shots if s.clip_index == fx.clip_index), fx.shot_id)
        out.append(replace(fx, shot_id=sid))
    return out

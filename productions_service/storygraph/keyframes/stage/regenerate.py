"""Human regenerate/edit of one keyframe: re-derive t..N, then cascade through the scene.

Frames before `t` are kept; frame `t` is re-derived (with the optional human instruction) and
every later frame re-chained from it, as a new `KeyframeSet` version. Because frame N always
changes, the following clips of the scene re-derive from the new shared start frame. Every
touched shot is marked stale (its clip must re-render) with a fresh repair budget.
"""

from __future__ import annotations

from ...errors import NotFound, ValidationFailed
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Scene, Shot
from ...schemas.keyframes import KeyframeSet
from ...shots.repair_state import mark_stale_and_reset
from ..render.renderer import RenderedKeyframe, RenderJob
from .frames import to_frame, to_rendered
from .stage import KeyframeStageDeps, ensure_shot, flag_manual_edit, plan_shot


def _prior(
    deps: KeyframeStageDeps, ks: KeyframeSet, t: int
) -> tuple[RenderedKeyframe, ...]:
    """Kept frames < t; only frame t-1 needs pixels (it is the edit source)."""
    out = [to_rendered(f) for f in ks.frames[:t]]
    if out:
        last = ks.frames[t - 1]
        out[-1] = to_rendered(last, deps.repo.blobs.get_bytes(last.uri))
    return tuple(out)


def _validate(ks: KeyframeSet | None, plan_hash: str, t: int) -> KeyframeSet:
    if ks is None:
        raise NotFound("no keyframes yet: run S8_KEYFRAMES first")
    if ks.plan_hash != plan_hash:
        raise ValidationFailed(
            ["keyframes are stale (graph changed): re-run S8_KEYFRAMES"]
        )
    if not 0 <= t < len(ks.frames):
        raise ValidationFailed([f"t={t} outside 0..{len(ks.frames) - 1}"])
    if t == 0 and ks.frames[0].shared_from:
        raise ValidationFailed(
            [
                f"frame 0 is shared with {ks.frames[0].shared_from}: edit that clip's last frame"
            ]
        )
    return ks


def _rederive(
    deps: KeyframeStageDeps, scene: Scene, shot: Shot, t: int, instruction: str
) -> KeyframeSet:
    sets = KeyframeSetRepo(deps.repo.store)
    inp, plan = plan_shot(deps.repo, scene, shot)
    active = _validate(sets.active_for_shot(shot.id), plan.plan_hash, t)
    job = RenderJob(prior=_prior(deps, active, t), start=t, instruction=instruction)
    frames = deps.renderer.render(inp, plan, job)
    stored = [
        to_frame(rk, plan.at(rk.t), deps.max_retries, human=rk.t >= t) for rk in frames
    ]
    stored[:t] = active.frames[:t]
    return sets.replace_frames(active, stored, f"human regenerate from t={t}")


def _touch(deps: KeyframeStageDeps, shot: Shot, ks: KeyframeSet, why: str) -> None:
    fresh = mark_stale_and_reset(shot, why)
    deps.repo.put_shot(fresh)
    if ks.needs_manual_edit:
        flag_manual_edit(deps.repo, fresh, ks)


def regenerate_from(
    deps: KeyframeStageDeps,
    shot_id: str,
    t: int,
    instruction: str = "",
    reset_repair: bool = True,
) -> KeyframeSet:
    """Re-derive `shot_id` frames t..N (+ following clips of the scene); returns its new set.

    `reset_repair=False` (automatic QA repair) keeps the shot's repair budget and render
    state: the repair loop re-renders it itself; later clips are still marked stale."""
    shot = deps.repo.get_shot(shot_id)
    scene = deps.repo.get_scene(shot.scene_id) if shot else None
    if shot is None or scene is None:
        raise NotFound(f"shot {shot_id} not found")
    ks = _rederive(deps, scene, shot, t, instruction.strip())
    if reset_repair:
        _touch(deps, shot, ks, f"keyframe t={t} regenerated")
    prev = ks
    later = [
        s
        for s in deps.repo.list_shots(scene_id=scene.id)
        if s.clip_index is not None and s.clip_index > (shot.clip_index or 0)
    ]
    for nxt in sorted(later, key=lambda s: s.clip_index or 0):
        prev, rendered = ensure_shot(deps, scene, nxt, prev)
        if rendered:
            _touch(
                deps, nxt, prev, f"previous clip keyframes changed ({shot_id} t={t})"
            )
    return ks

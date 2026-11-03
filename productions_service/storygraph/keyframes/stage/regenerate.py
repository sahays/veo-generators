"""Human regenerate/edit of one keyframe: re-derive t..N, then cascade through the scene.

Frames before `t` are kept; frame `t` is re-derived (with the optional human instruction) and
every later frame regenerated from the scene plate (previous frame as pose reference only), as
a new `KeyframeSet` version. Because frame N always
changes, the following clips of the scene re-derive from the new shared start frame. Every
touched shot is marked stale (its clip must re-render) with a fresh repair budget.
"""

from __future__ import annotations

from ...errors import NotFound, ValidationFailed
from ...repo.keyframe_sets import KeyframeSetRepo
from ...schema import Scene, Shot
from ...schemas.keyframes import KeyframeSet
from ..render.renderer import RenderJob
from .frames import to_frame
from .outcomes import settle_shot
from .resume import prior_frames
from .stage import KeyframeStageDeps, SceneContext, ensure_shot, scene_context


TIME_EPS = 1e-3  # keyframe times are rounded to milliseconds


def frame_index(ks: KeyframeSet, t: float) -> int:
    """Index of the frame at clip time `t` (a set holds only a handful of frames)."""
    for idx, frame in enumerate(ks.frames):
        if abs(frame.t - t) <= TIME_EPS:
            return idx
    times = ", ".join(f"{f.t:g}" for f in ks.frames)
    raise ValidationFailed([f"no keyframe at t={t:g} (keyframes at {times})"])


def _validate(
    ks: KeyframeSet | None, plan_hash: str, t: float
) -> tuple[KeyframeSet, int]:
    if ks is None:
        raise NotFound("no keyframes yet: run S8_KEYFRAMES first")
    if ks.failure_reason:
        raise ValidationFailed(
            [f"keyframes failed ({ks.failure_reason}): resume S8_KEYFRAMES first"]
        )
    if ks.plan_hash != plan_hash:
        raise ValidationFailed(
            ["keyframes are stale (graph changed): re-run S8_KEYFRAMES"]
        )
    idx = frame_index(ks, t)
    if idx == 0 and ks.frames[0].shared_from:
        raise ValidationFailed(
            [
                f"frame 0 is shared with {ks.frames[0].shared_from}: edit that clip's last frame"
            ]
        )
    return ks, idx


def _context(deps: KeyframeStageDeps, scene: Scene) -> SceneContext:
    ctx = scene_context(deps, scene)
    if ctx is None:
        raise NotFound(f"scene {scene.id} has no clips")
    return ctx


def _rederive(
    deps: KeyframeStageDeps, ctx: SceneContext, shot: Shot, t: float, instruction: str
) -> KeyframeSet:
    sets = KeyframeSetRepo(deps.repo.store)
    sp = ctx.plans.get(shot.id)
    if sp is None:
        raise NotFound(f"shot {shot.id} is not a clip")
    inp, plan = sp.inp, sp.plan
    active, idx = _validate(sets.active_for_shot(shot.id), plan.plan_hash, t)
    job = RenderJob(
        plate=ctx.plate,
        prior=prior_frames(deps.repo, active, idx),
        start=idx,
        instruction=instruction,
    )
    frames = deps.renderer.render(inp, plan, job)
    stored = [
        to_frame(rk, plan.at(rk.t), deps.max_retries, human=rk.t >= t) for rk in frames
    ]
    stored[:idx] = active.frames[:idx]
    return sets.replace_frames(active, stored, f"human regenerate from t={t}")


def _touch(deps: KeyframeStageDeps, shot: Shot, ks: KeyframeSet, why: str) -> None:
    settle_shot(deps.repo, deps.repo.get_shot(shot.id) or shot, ks, why)


def regenerate_from(
    deps: KeyframeStageDeps,
    shot_id: str,
    t: float,
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
    ctx = _context(deps, scene)
    ks = _rederive(deps, ctx, shot, t, instruction.strip())
    if reset_repair:
        _touch(deps, shot, ks, f"keyframe t={t} regenerated")
    prev = ks
    later = [
        s
        for s in deps.repo.list_shots(scene_id=scene.id)
        if s.clip_index is not None and s.clip_index > (shot.clip_index or 0)
    ]
    for nxt in sorted(later, key=lambda s: s.clip_index or 0):
        prev, rendered = ensure_shot(deps, ctx, nxt, prev)
        if rendered:
            _touch(
                deps, nxt, prev, f"previous clip keyframes changed ({shot_id} t={t})"
            )
    return ks

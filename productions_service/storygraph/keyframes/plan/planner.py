"""Pure, deterministic keyframe planner driven by StoryGraph state.

Keyframe times come from `sampling` (event-driven by default: clip start/end, state changes,
beat boundaries, large-motion midpoints; or legacy every second). For each time `t` the
planner derives: which beat is active and how far through it we are (`timing.locate`), which
graph snapshot holds (pre-beat before the beat midpoint, post-beat after it), every
character's wardrobe/pose/position/holdings, the exact set of objects alive (each exactly
once, with holder/placement from graph state, `state`), the setting, the camera framing and
why the moment was selected (`event_label`, `event_kind`). The first keyframe shows the
clip's opening state and the last its closing state by construction. No I/O, no randomness.
"""

from __future__ import annotations

import hashlib

from .models import (
    BeatSpan,
    CameraKey,
    CastInput,
    CharacterKey,
    Keyframe,
    KeyframePlan,
    ObjectKey,
    PlanInput,
    StateSnapshot,
)
from .motion import COLUMN_X, Tracks
from .sampling.models import DENSE, Candidate, SamplingCfg
from .sampling.times import clock, sample_times
from .state import exposed_ids, names_of, objects_at
from .timing import locate, snapshot_index

__all__ = ["objects_at", "plan_hash", "plan_keyframes", "keyframe_delta"]

_STAGES = ((0.34, "starting:"), (0.67, "midway:"), (1.0, "finishing:"))


def _actor_pose(beat: BeatSpan, phase: float) -> str:
    """Only this character's own action (scene-level pre/post state text is never a pose)."""
    if phase <= 0.0:
        return f"about to: {beat.action}"
    if phase >= 1.0:
        return f"has just finished: {beat.action}"
    stage = next(label for bound, label in _STAGES if phase < bound or bound == 1.0)
    return f"{stage} {beat.action}"


def _pose(
    cast: CastInput, beat: BeatSpan | None, phase: float, names: dict[str, str]
) -> str:
    if beat is None:
        return "stands naturally in place"
    if cast.entity_id == beat.actor_id:
        return _actor_pose(beat, phase)
    actor = names.get(beat.actor_id, beat.actor_id)
    if cast.entity_id == beat.target_id:
        return f"engaged with {actor}, responding to the action"
    return f"stays in place, attentive to {actor}"


def characters_at(
    inp: PlanInput,
    beat: BeatSpan | None,
    phase: float,
    snap: StateSnapshot,
    xs: dict[str, float] | None = None,
) -> list[CharacterKey]:
    names = names_of(inp)
    xs = xs or {}
    out: list[CharacterKey] = []
    for cast in inp.cast:
        held = snap.states.get(cast.entity_id, {}).get("holding")
        out.append(
            CharacterKey(
                entity_id=cast.entity_id,
                name=cast.name,
                wardrobe=cast.wardrobe,
                pose=_pose(cast, beat, phase, names),
                position=cast.position,
                holding=[held] if held else [],
                ref_asset_id=cast.ref_asset_id,
                x=xs.get(cast.entity_id, COLUMN_X[cast.position]),
            )
        )
    return out


def camera_at(inp: PlanInput, progress: float) -> CameraKey:
    """Keyframes keep one framing per shot; the move itself (`movement`, `progress`) is
    performed by the video model, so per-second edits never re-frame the image."""
    cam = inp.camera
    framing = f"{cam.shot_size} {cam.angle}-angle, {cam.lens_mm}mm"
    return CameraKey(
        shot_size=cam.shot_size,
        angle=cam.angle,
        movement=cam.movement,
        progress=round(progress, 3),
        framing=framing,
    )


def _setting(inp: PlanInput) -> str:
    when = f", {inp.time_of_day}" if inp.time_of_day else ""
    return f"{inp.location_name}{when}"


def _char_delta(
    prev: CharacterKey, cur: CharacterKey, names: dict[str, str]
) -> list[str]:
    out: list[str] = []
    if cur.pose != prev.pose:
        out.append(f"{cur.name}: {cur.pose}")
    if abs(cur.x - prev.x) > 0.02:
        out.append(f"{cur.name} moves to x={cur.x:.2f} of the frame width")
    if cur.holding != prev.holding:
        held = ", ".join(names.get(h, h) for h in cur.holding)
        out.append(
            f"{cur.name} now holds {held}"
            if held
            else f"{cur.name}'s hands are now empty"
        )
    return out


def _object_delta(prev: list[ObjectKey], cur: list[ObjectKey]) -> list[str]:
    before = {o.entity_id: o for o in prev}
    now = {o.entity_id: o for o in cur}
    out = [f"{before[i].name} is no longer present" for i in before if i not in now]
    for oid, obj in now.items():
        old = before.get(oid)
        if old is None:
            out.append(f"{obj.name} appears, {obj.placement}")
        elif (old.placement, old.visible) != (obj.placement, obj.visible):
            hidden = "" if obj.visible else " (out of sight)"
            out.append(f"{obj.name}: {obj.placement}{hidden}")
    return out


def keyframe_delta(prev: Keyframe, cur: Keyframe, names: dict[str, str]) -> list[str]:
    """Human-readable changes from `prev` to `cur` (empty = identical frame)."""
    before = {c.entity_id: c for c in prev.characters}
    out: list[str] = []
    for char in cur.characters:
        old = before.get(char.entity_id)
        out += (
            [f"{char.name} enters the frame"]
            if old is None
            else _char_delta(old, char, names)
        )
    out += _object_delta(prev.objects, cur.objects)
    if cur.camera.framing != prev.camera.framing:
        out.append(f"camera: {cur.camera.framing}")
    return out


def _keyframe(
    inp: PlanInput, pick: Candidate, last_t: float, xs: dict[str, float]
) -> Keyframe:
    t = pick.t
    spans = [(b.t_start, b.t_end) for b in inp.beats]
    beat_idx, phase = locate(t if t < last_t else inp.duration_s, spans)
    snap_idx = 0 if t == 0 else len(inp.snapshots) - 1 if t == last_t else None
    if snap_idx is None:
        snap_idx = min(snapshot_index(beat_idx, phase), len(inp.snapshots) - 1)
    snap = inp.snapshots[snap_idx] if inp.snapshots else StateSnapshot(order=0)
    beat = inp.beats[beat_idx] if inp.beats else None
    return Keyframe(
        t=t,
        beat_index=beat_idx,
        phase=phase,
        snapshot_index=snap_idx,
        characters=characters_at(inp, beat, phase, snap, xs),
        objects=objects_at(inp, snap, exposed_ids(inp, beat)),
        setting=_setting(inp),
        camera=camera_at(inp, t / last_t if last_t else 0.0),
        event_label=pick.label,
        event_kind=pick.kind,
    )


def plan_hash(plan: KeyframePlan) -> str:
    body = plan.model_copy(update={"plan_hash": ""}).model_dump_json()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def plan_keyframes(inp: PlanInput, sampling: SamplingCfg = DENSE) -> KeyframePlan:
    """Build the `KeyframePlan` for one clip at the times `sampling` selects.

    The default is dense 1 fps (t = 0..round(duration)) for analysis callers (plate spec,
    previz); production planning passes the configured sampling (`stage.scene_plans`)."""
    last_t, step = clock(inp, sampling)
    names = names_of(inp)
    track = Tracks(inp, last_t, step)
    frames: list[Keyframe] = []
    for pick in sample_times(inp, sampling, track.displacement):
        frame = _keyframe(inp, pick, last_t, track.at(pick.t))
        if frames:
            frame = frame.model_copy(
                update={"delta": keyframe_delta(frames[-1], frame, names)}
            )
        frames.append(frame)
    plan = KeyframePlan(
        project_id=inp.project_id,
        scene_id=inp.scene_id,
        shot_id=inp.shot_id,
        clip_index=inp.clip_index,
        duration_s=inp.duration_s,
        prompt_version_id=inp.prompt_version_id,
        keyframes=frames,
    )
    return plan.model_copy(update={"plan_hash": plan_hash(plan)})

"""Per-clip 3D blocking from the 1 fps keyframe plan (pure, deterministic).

Characters: plan x (already interpolated + rate-limited by `plan.motion`) is projected onto
the stage line through the master camera; an actor working at a set piece (or a prop on one)
steps forward to just in front of it, depth changes rate-limited to `MAX_STEP_Y` m/s, and
every step is bounded by the character's body speed (`archetype.character_body`: a dog
trots faster than a small robot). `walks.apply_walks` then adds the walks the 2D plan
cannot express (to props / entrances). Facing follows motion, else the beat target, else
the camera; an actor pushing something faces what it pushes even while moving. Pose from
`poses.body_pose` (reach when standing at the beat target with no other action pose).
Character colours are kept distinct per clip. Props are delegated to `props.prop_tracks`.
O(seconds × entities).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Final

from ...keyframes.plan.models import BeatSpan, Keyframe, KeyframePlan, PlanInput
from ...keyframes.plan.timing import second_index
from ...schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    CharacterKey,
    CharacterTrack,
    LocationLayout,
    Pose,
    Vec3,
)
from ..layout.colors import distinct_colors
from .archetype import Body, character_body
from .poses import body_pose
from .project import Aspect
from .props import prop_tracks, target_xy
from .stage import Stage, build_stage
from .walks import apply_walks, bound_speed

MAX_STEP_Y: Final[float] = 0.75
MOVE_EPS: Final[float] = 0.05
PUSH_REACH: Final[float] = 1.2  # m from the target centre: hands on it
XY = tuple[float, float]
Orient = tuple[float | None, float | None, bool]  # motion, look heading, contact
Walked = tuple[dict[str, list[XY]], set[tuple[str, int]]]


def _beat(inp: PlanInput, frame: Keyframe) -> BeatSpan | None:
    return inp.beats[frame.beat_index] if inp.beats else None


def _x_img(frame: Keyframe, cid: str) -> float:
    return next(c.x for c in frame.characters if c.entity_id == cid)


def _want_y(
    stage: Stage, inp: PlanInput, frame: Keyframe, target_id: str, current: float
) -> float:
    """In front of the target's piece; back to the stage line for a character target;
    otherwise (a free or just-picked-up prop) stay where the actor is."""
    near = stage.approach_y(frame, target_id)
    if near is not None:
        return near
    return stage.line_y if any(c.entity_id == target_id for c in inp.cast) else current


def _depths(stage: Stage, inp: PlanInput, plan: KeyframePlan, cid: str) -> list[float]:
    """Desired depth per second (stage line, or in front of the worked-at piece), limited."""
    out: list[float] = []
    want = stage.line_y
    for frame in plan.keyframes:
        beat = _beat(inp, frame)
        acting = beat is not None and beat.actor_id == cid and frame.t >= beat.t_start
        if acting and beat is not None and beat.target_id:
            want = _want_y(stage, inp, frame, beat.target_id, want)
        prev = out[-1] if out else want
        out.append(round(prev + max(-MAX_STEP_Y, min(MAX_STEP_Y, want - prev)), 3))
    return out


def _positions(
    stage: Stage, inp: PlanInput, plan: KeyframePlan, bodies: Mapping[str, Body]
) -> dict[str, list[XY]]:
    """Plan path per character on the floor, each step bounded by its body speed."""
    out: dict[str, list[XY]] = {}
    for c in inp.cast:
        ys = _depths(stage, inp, plan, c.entity_id)
        half = bodies[c.entity_id].height_m / 2
        path = [
            (round(stage.world_x(_x_img(f, c.entity_id), y, half), 3), y)
            for f, y in zip(plan.keyframes, ys, strict=True)
        ]
        out[c.entity_id] = bound_speed(path, bodies[c.entity_id].max_speed)
    return out


def _heading(src: XY, dst: XY) -> float | None:
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    if math.hypot(dx, dy) <= MOVE_EPS:
        return None
    return round(math.degrees(math.atan2(dx, -dy)), 1)


def _step(path: list[XY], i: int) -> float | None:
    """Heading of the move during second i -> i+1 (None when standing / last second)."""
    return _heading(path[i], path[i + 1]) if i + 1 < len(path) else None


def _look_target(
    stage: Stage, frame: Keyframe, beat: BeatSpan | None, cid: str, pos: dict[str, XY]
) -> XY | None:
    if beat is None or not 0.0 < frame.phase <= 1.0:
        return None
    if beat.actor_id == cid and beat.target_id:
        return pos.get(beat.target_id) or target_xy(stage, frame, beat.target_id)
    return pos.get(beat.actor_id) if beat.target_id == cid else None


def _target_moves(
    stage: Stage, inp: PlanInput, plan: KeyframePlan, frame: Keyframe, cid: str
) -> bool:
    """`cid`'s beat target (set piece / resting prop) is displaced during this second."""
    beat = _beat(inp, frame)
    if beat is None or beat.actor_id != cid or not beat.target_id:
        return False
    nxt = second_index(frame.t) + 1
    if nxt >= len(plan.keyframes):
        return False
    a = target_xy(stage, frame, beat.target_id)
    b = target_xy(stage, plan.keyframes[nxt], beat.target_id)
    return a is not None and b is not None and math.dist(a, b) > MOVE_EPS


def _orient(
    stage: Stage, inp: PlanInput, plan: KeyframePlan, frame: Keyframe, walked: Walked
) -> Callable[[str], Orient]:
    """Per character: (motion heading, heading to its beat target, pushing contact)."""
    paths = walked[0]
    now = {k: v[second_index(frame.t)] for k, v in paths.items()}

    def of(cid: str) -> Orient:
        target = _look_target(stage, frame, _beat(inp, frame), cid, now)
        looked = _heading(now[cid], target) if target else None
        near = target is not None and math.dist(now[cid], target) <= PUSH_REACH
        contact = near and _target_moves(stage, inp, plan, frame, cid)
        return _step(paths[cid], second_index(frame.t)), looked, contact

    return of


def _pose_facing(text: str, reach: bool, orient: Orient) -> tuple[Pose, float]:
    """Walkers face their motion; a pusher moving its target faces it; standing actors
    face their target (else the camera) and reach at it when no other pose applies."""
    moving, looked, contact = orient
    pose = body_pose(text, moving is not None, contact)
    if pose == "walk" and moving is not None:
        return pose, moving
    if pose == "stand" and reach:
        pose = "reach"
    return pose, looked if looked is not None else (moving or 0.0)


def _character_keys(
    stage: Stage, inp: PlanInput, plan: KeyframePlan, cid: str, walked: Walked
) -> list[CharacterKey]:
    paths, reach = walked
    keys: list[CharacterKey] = []
    for frame in plan.keyframes:
        ck = next(c for c in frame.characters if c.entity_id == cid)
        orient = _orient(stage, inp, plan, frame, walked)(cid)
        at_target = orient[0] is None and (cid, second_index(frame.t)) in reach
        pose, facing = _pose_facing(ck.pose, at_target, orient)
        x, y = paths[cid][second_index(frame.t)]
        keys.append(
            CharacterKey(
                t=float(frame.t),
                position=Vec3(x=x, y=y, z=0.0),
                facing_deg=facing,
                pose=pose,
                holding=ck.holding[0] if ck.holding else None,
            )
        )
    return keys


def blocking_track(
    inp: PlanInput,
    plan: KeyframePlan,
    layout: LocationLayout,
    colors: dict[str, str],
    aspect: Aspect = "16:9",
    master: CameraRig | None = None,
    aspects: Mapping[str, float] | None = None,
) -> BlockingTrack:
    """3D blocking of one clip: one keyed track per character and per dynamic prop.
    `master` = calibrated plate camera (else synthetic); `aspects` = sheet width/height."""
    stage = build_stage(inp, layout, aspect, master, aspects)
    bodies = {
        c.entity_id: character_body(c.name, c.description, c.wardrobe) for c in inp.cast
    }
    speeds = {cid: b.max_speed for cid, b in bodies.items()}
    base = _positions(stage, inp, plan, bodies)
    walked = apply_walks(stage, inp, plan, base, speeds)
    cast_colors = distinct_colors(colors, [c.entity_id for c in inp.cast])
    chars = [
        CharacterTrack(
            entity_id=c.entity_id,
            name=c.name,
            color=cast_colors[c.entity_id],
            height_m=bodies[c.entity_id].height_m,
            archetype=bodies[c.entity_id].archetype,
            keys=_character_keys(stage, inp, plan, c.entity_id, walked),
        )
        for c in inp.cast
    ]
    return BlockingTrack(
        shot_id=inp.shot_id,
        scene_id=inp.scene_id,
        clip_index=inp.clip_index,
        duration_s=inp.duration_s,
        characters=chars,
        props=prop_tracks(stage, inp, plan, chars, colors),
    )

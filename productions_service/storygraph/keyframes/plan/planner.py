"""Pure, deterministic 1 fps keyframe planner driven by StoryGraph state.

For every integer second `t` of a clip the planner derives: which beat is active and how far
through it we are (`timing.locate`), which graph snapshot holds (pre-beat before the beat
midpoint, post-beat after it), every character's wardrobe/pose/position/holdings, the exact
set of objects alive at that second (each exactly once, with holder/placement from graph
state), the setting and the camera framing. Second 0 shows the clip's opening state and the
last second its closing state by construction. No I/O, no randomness.
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
from .motion import COLUMN_X, tracks
from .timing import locate, second_count, snapshot_index

_HIDDEN_PLACE = ("inside", "hidden", "concealed", "buried")
_CONTAINED = ("drawer", "box", "chest", "bag", "pocket", "under the lid")
_HIDDEN_HOLD = (
    "behind back",
    "behind his back",
    "behind her back",
    "hidden",
    "concealed",
)
_ABSENT = frozenset({"false", "no", "0", "absent", "gone", "destroyed", "consumed"})
_TIGHT = frozenset({"ECU", "CU", "MCU"})
_STAGES = ((0.34, "starting:"), (0.67, "midway:"), (1.0, "finishing:"))


def _names(inp: PlanInput) -> dict[str, str]:
    out = {inp.location_id: inp.location_name}
    out.update({c.entity_id: c.name for c in inp.cast})
    out.update({o.entity_id: o.name for o in inp.objects})
    return out


def _holders(snap: StateSnapshot) -> dict[str, str]:
    """`object id -> holder id` from every `holding` fact in the snapshot."""
    return {st["holding"]: eid for eid, st in snap.states.items() if st.get("holding")}


def _alive(inp: PlanInput, st: dict[str, str], held: bool) -> bool:
    if (st.get("alive_present") or "").lower() in _ABSENT:
        return False
    return held or st.get("location") == inp.location_id


def _placement(st: dict[str, str], holder: str | None, names: dict[str, str]) -> str:
    if holder:
        return f"held by {names.get(holder, holder)}"
    parts: list[str] = []
    support = st.get("supported_by")
    if support:
        parts.append(f"on the {names.get(support, support)}")
    if st.get("sub_location"):
        parts.append(st["sub_location"])
    return ", ".join(parts) or "in its place in the room"


def _visible(st: dict[str, str], holder_state: dict[str, str] | None) -> bool:
    """Hidden when its holder conceals it, or it is contained in another object."""
    if holder_state is not None:
        where = (holder_state.get("sub_location") or "").lower()
        return not any(k in where for k in _HIDDEN_HOLD)
    where = (st.get("sub_location") or "").lower()
    contained = bool(st.get("supported_by")) and any(k in where for k in _CONTAINED)
    return not contained and not any(k in where for k in _HIDDEN_PLACE)


def exposed_ids(inp: PlanInput, beat: BeatSpan | None) -> frozenset[str]:
    """Objects the active beat acts on or names: they are visible while it plays."""
    if beat is None:
        return frozenset()
    text = f"{beat.action} {beat.pre_state} {beat.post_state}".lower()
    named = {o.entity_id for o in inp.objects if o.name.lower() in text}
    return frozenset(named | ({beat.target_id} if beat.target_id else set()))


def objects_at(
    inp: PlanInput, snap: StateSnapshot, exposed: frozenset[str] = frozenset()
) -> list[ObjectKey]:
    """Objects alive at `snap` (keyed by entity id, so each appears exactly once)."""
    names, holders = _names(inp), _holders(snap)
    cast_ids = {c.entity_id for c in inp.cast}
    tight = inp.camera.shot_size in _TIGHT
    out: list[ObjectKey] = []
    for obj in inp.objects:
        st = snap.states.get(obj.entity_id, {})
        holder = holders.get(obj.entity_id)
        if not _alive(inp, st, holder is not None):
            continue
        in_frame = not tight or obj.focus or holder in cast_ids
        holder_state = snap.states.get(holder, {}) if holder else None
        out.append(
            ObjectKey(
                entity_id=obj.entity_id,
                name=obj.name,
                placement=_placement(st, holder, names),
                holder_id=holder,
                visible=obj.entity_id in exposed or _visible(st, holder_state),
                in_frame=in_frame,
                x=None if holder else inp.layout.get(obj.entity_id),
            )
        )
    return out


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
    names = _names(inp)
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


def _keyframe(inp: PlanInput, t: int, last_t: int, xs: dict[str, float]) -> Keyframe:
    spans = [(b.t_start, b.t_end) for b in inp.beats]
    beat_idx, phase = locate(float(t) if t < last_t else inp.duration_s, spans)
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
    )


def plan_hash(plan: KeyframePlan) -> str:
    body = plan.model_copy(update={"plan_hash": ""}).model_dump_json()
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def plan_keyframes(inp: PlanInput) -> KeyframePlan:
    """Build the 1 fps `KeyframePlan` for one clip (t = 0..round(duration))."""
    last_t = second_count(inp.duration_s) - 1
    names = _names(inp)
    paths = tracks(inp, last_t)
    frames: list[Keyframe] = []
    for t in range(last_t + 1):
        frame = _keyframe(inp, t, last_t, {cid: xs[t] for cid, xs in paths.items()})
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

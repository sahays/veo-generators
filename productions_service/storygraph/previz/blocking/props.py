"""Dynamic prop tracks (pure): held -> in the holder's hand, on a set piece -> on top of it.

Per second, a prop alive in the plan is placed by the first rule that applies:
1. held (`ObjectKey.holder_id`): at the holder's hand (side + forward offset by facing);
2. `"on the <set piece>"`: on top of that piece, props sharing a piece spread along X;
3. a layout x from the plate: on the floor just behind the stage line at that x;
4. otherwise where it was last released (below the hand), else its home spot (a stable
   hashed floor slot behind the stage line, which actors targeting it walk to).
Props absent from a second keep their last position, invisible. One track per prop id.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Final

from ...keyframes.plan.models import (
    Keyframe,
    KeyframePlan,
    ObjectInput,
    ObjectKey,
    PlanInput,
)
from ...keyframes.plan.timing import second_index
from ...schemas.previz_scene import (
    CharacterKey,
    CharacterTrack,
    PropKey,
    PropTrack,
    SetPiece,
    Vec3,
)
from ..layout.colors import color_for
from .stage import Stage

PROP_BEHIND: Final[float] = 0.6
SLOT_STEP: Final[float] = 0.4
Slots = dict[str, tuple[SetPiece, int, int]]


def anchor_xy(
    stage: Stage, frame: Keyframe, entity_id: str
) -> tuple[float, float] | None:
    piece = stage.anchor_piece(frame, entity_id)
    return (piece.position.x, piece.position.y) if piece else None


def hand_position(key: CharacterKey, height: float) -> Vec3:
    """Right hand: forward/side offsets rotated by facing (reach extends the arm up/out)."""
    f = math.radians(key.facing_deg)
    fwd = 0.45 if key.pose == "reach" else 0.18
    side = 0.2 * height / 1.6
    fx, fy, rx, ry = math.sin(f), -math.cos(f), -math.cos(f), -math.sin(f)
    return Vec3(
        x=round(key.position.x + fx * fwd + rx * side, 3),
        y=round(key.position.y + fy * fwd + ry * side, 3),
        z=round(height * (0.75 if key.pose == "reach" else 0.5), 3),
    )


def _slots(stage: Stage, frame: Keyframe) -> Slots:
    groups: dict[str, list[str]] = {}
    for o in frame.objects:
        piece = None if o.holder_id else stage.support_piece(o.placement)
        if piece is not None and o.entity_id not in stage.pieces:
            groups.setdefault(piece.entity_id, []).append(o.entity_id)
    out: Slots = {}
    for pid, ids in groups.items():
        ordered = sorted(ids)
        out |= {
            oid: (stage.pieces[pid], i, len(ordered)) for i, oid in enumerate(ordered)
        }
    return out


def _on_piece(slot: tuple[SetPiece, int, int], size: Vec3) -> Vec3:
    piece, i, n = slot
    step = min(SLOT_STEP, piece.size.x / (n + 1))
    x = piece.position.x + (i - (n - 1) / 2) * step
    return Vec3(
        x=round(x, 3), y=piece.position.y, z=round(piece.size.z + size.z / 2, 3)
    )


def prop_home(stage: Stage, oid: str, size: Vec3) -> Vec3:
    """A prop's floor spot when nothing places it: a stable hashed x behind the stage line
    (independent of the characters, so an actor can walk TO it)."""
    frac = int(hashlib.sha256(oid.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    y = stage.clamp_y(stage.line_y + PROP_BEHIND)
    return Vec3(
        x=round(stage.world_x(0.15 + 0.7 * frac, y, size.z / 2), 3), y=y, z=size.z / 2
    )


def _free(
    stage: Stage,
    ok: ObjectKey,
    size: Vec3,
    slot: tuple[SetPiece, int, int] | None,
    fallback: Vec3,
) -> Vec3:
    if slot is not None:
        return _on_piece(slot, size)
    if ok.x is not None:
        y = stage.clamp_y(stage.line_y + PROP_BEHIND)
        return Vec3(x=round(stage.world_x(ok.x, y, size.z / 2), 3), y=y, z=size.z / 2)
    return fallback


def resting_position(stage: Stage, frame: Keyframe, oid: str) -> Vec3 | None:
    """Where an unheld prop alive at `frame` stands (None if held or absent)."""
    ok = next((o for o in frame.objects if o.entity_id == oid), None)
    if ok is None or ok.holder_id or oid in stage.pieces:
        return None
    size = stage.prop_shape(oid, ok.name).size
    slot = _slots(stage, frame).get(oid)
    return _free(stage, ok, size, slot, prop_home(stage, oid, size))


def target_xy(stage: Stage, frame: Keyframe, oid: str) -> tuple[float, float] | None:
    """Floor position of a set piece, a prop on one, or a resting prop."""
    anchored = anchor_xy(stage, frame, oid)
    rest = resting_position(stage, frame, oid) if anchored is None else None
    return anchored or ((rest.x, rest.y) if rest else None)


def _track(
    stage: Stage,
    plan: KeyframePlan,
    obj: ObjectInput,
    chars: Mapping[str, CharacterTrack],
    slots: Sequence[Slots],
) -> list[PropKey]:
    size = stage.prop_shape(obj.entity_id, obj.name).size
    free = prop_home(stage, obj.entity_id, size)
    last = free
    keys: list[PropKey] = []
    for frame in plan.keyframes:
        ok = next((o for o in frame.objects if o.entity_id == obj.entity_id), None)
        holder = chars.get(ok.holder_id) if ok and ok.holder_id else None
        if ok is None:
            keys.append(PropKey(t=float(frame.t), position=last, visible=False))
            continue
        if holder is not None:
            last = hand_position(holder.keys[second_index(frame.t)], holder.height_m)
            free = last.model_copy(update={"z": size.z / 2})
        else:
            last = _free(
                stage, ok, size, slots[second_index(frame.t)].get(obj.entity_id), free
            )
        keys.append(
            PropKey(
                t=float(frame.t),
                position=last,
                holder_id=holder.entity_id if holder else None,
                visible=ok.visible,
            )
        )
    return keys


def prop_tracks(
    stage: Stage,
    inp: PlanInput,
    plan: KeyframePlan,
    chars: Sequence[CharacterTrack],
    colors: Mapping[str, str],
) -> list[PropTrack]:
    """One typed `PropTrack` per non-set-piece object of the clip (sorted by id)."""
    by_id = {c.entity_id: c for c in chars}
    slots = [_slots(stage, f) for f in plan.keyframes]
    props = sorted(
        (o for o in inp.objects if o.entity_id not in stage.pieces),
        key=lambda o: o.entity_id,
    )
    tracks: list[PropTrack] = []
    for o in props:
        shaped = stage.prop_shape(o.entity_id, o.name)
        tracks.append(
            PropTrack(
                entity_id=o.entity_id,
                name=o.name,
                color=color_for(colors, o.entity_id),
                kind=shaped.kind,
                params=shaped.params,
                size=shaped.size,
                keys=_track(stage, plan, o, by_id, slots),
            )
        )
    return tracks

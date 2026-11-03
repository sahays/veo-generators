"""bpy actors: archetype characters (rig + procedural motion keys) and kind-built props."""

from __future__ import annotations

import math
from typing import Any

import geo
import motion
import palette
import parts as part_tables
import rigs

Obj = Any
Json = dict[str, Any]
Built = list[tuple[Obj, str]]


def frame_at(t: float, fps: int) -> float:
    """Scene time (s) -> Blender frame (frame 1 is t = 0)."""
    return 1.0 + t * fps


def vec(
    data: Json | None, default: tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> tuple[float, float, float]:
    """Vec3 JSON -> tuple."""
    if not data:
        return default
    return (
        float(data.get("x", 0.0)),
        float(data.get("y", 0.0)),
        float(data.get("z", 0.0)),
    )


def build_rig(track: Json) -> tuple[dict[str, Obj], Built]:
    """Root (scaled to height) + joint empties + coloured parts for the track's archetype."""
    eid = str(track.get("entity_id", "char"))
    color = str(track.get("color", "#4060c0"))
    height = max(float(track.get("height_m", 1.6)), 0.2)
    joints, rig_parts = rigs.rig_for(str(track.get("archetype", "human")))
    nodes = {"root": geo.add_empty(f"char_{eid}")}
    nodes["root"].scale = (height, height, height)
    for name, parent, pivot in joints:
        nodes[name] = geo.place(
            geo.add_empty(f"char_{eid}_{name}", nodes[parent]), pivot, (1.0, 1.0, 1.0)
        )
    built: Built = []
    for name, shape, node, centre, size, rot, role in rig_parts:
        flat = palette.tone(color, role)
        obj = geo.add_mesh(f"char_{eid}_{name}", shape, flat, nodes[node])
        built.append((geo.place(obj, centre, size, rot), flat))
    return nodes, built


def key_root(root: Obj, keys: list[Json], fps: int) -> None:
    """Root location + heading at each blocking key (bezier between keys)."""
    headings = motion.unwrap_angles([float(k.get("facing_deg", 0.0)) for k in keys])
    for key, heading in zip(keys, headings):
        frame = frame_at(float(key.get("t", 0.0)), fps)
        root.location = vec(key.get("position"))
        root.rotation_euler = (0.0, 0.0, math.radians(heading))
        root.keyframe_insert("location", frame=frame)
        root.keyframe_insert("rotation_euler", index=2, frame=frame)


def key_samples(
    nodes: dict[str, Obj], samples: list[motion.MotionSample], fps: int
) -> None:
    """Body bob/lean/squash + joint rotations per motion sample."""
    body = nodes["body"]
    joint_names = sorted({n for s in samples for n in s.pose.joints} & set(nodes))
    for sample in samples:
        frame = frame_at(sample.t, fps)
        pose = sample.pose
        body.location = (0.0, 0.0, pose.bob)
        body.rotation_euler = (math.radians(pose.lean), 0.0, 0.0)
        body.scale = (1.0, 1.0, pose.squash)
        body.keyframe_insert("location", index=2, frame=frame)
        body.keyframe_insert("rotation_euler", index=0, frame=frame)
        body.keyframe_insert("scale", index=2, frame=frame)
        for name in joint_names:
            nodes[name].rotation_euler = (
                math.radians(pose.joints.get(name, 0.0)),
                0.0,
                0.0,
            )
            nodes[name].keyframe_insert("rotation_euler", index=0, frame=frame)


def reach_targets(
    keys: list[Json], props: list[Json]
) -> dict[int, tuple[float, float, float]]:
    """Key index -> world position of the prop that key is holding/reaching for."""
    latest: dict[str, list[Json]] = {
        str(p.get("entity_id")): sorted(
            p.get("keys") or [], key=lambda k: float(k.get("t", 0.0))
        )
        for p in props
    }
    out: dict[int, tuple[float, float, float]] = {}
    for idx, key in enumerate(keys):
        track = latest.get(str(key.get("holding")))
        if not track:
            continue
        t = float(key.get("t", 0.0))
        before = [k for k in track if float(k.get("t", 0.0)) <= t] or track[:1]
        out[idx] = vec(before[-1].get("position"))
    return out


def build_character(
    track: Json, fps: int, duration: float, props: list[Json]
) -> tuple[Obj, Built]:
    """Rig + keys; returns (hand node for held props, [(object, flat colour)])."""
    nodes, built = build_rig(track)
    keys = sorted(track.get("keys") or [], key=lambda k: float(k.get("t", 0.0)))
    if keys:
        key_root(nodes["root"], keys, fps)
        height = nodes["root"].scale[0]
        samples = motion.sample_motion(
            str(track.get("archetype", "human")),
            height,
            keys,
            duration,
            reach_targets(keys, props),
        )
        key_samples(nodes, samples, fps)
    return nodes["hand_r"], built


def set_constant(obj: Obj, data_path: str) -> None:
    """Make every keyframe on `data_path` step (no interpolation)."""
    action = obj.animation_data.action if obj.animation_data else None
    for fcurve in action.fcurves if action else []:
        if fcurve.data_path == data_path:
            for point in fcurve.keyframe_points:
                point.interpolation = "CONSTANT"


def build_prop(track: Json, hands: dict[str, Obj], fps: int) -> Built:
    """Kind-built prop centred on its key position; Copy Location to the holder's hand."""
    eid = str(track.get("entity_id", "prop"))
    size = vec(track.get("size"), (0.25, 0.25, 0.25))
    root = geo.add_empty(f"prop_{eid}")
    table = part_tables.piece_parts(
        str(track.get("kind", "box")), size, track.get("params") or {}
    )
    offset = [
        (n, s, (c[0], c[1], c[2] - size[2] / 2), sz, r) for n, s, c, sz, r in table
    ]
    built = geo.build_parts(
        f"prop_{eid}", offset, str(track.get("color", "#c04040")), root
    )
    keys = sorted(track.get("keys") or [], key=lambda k: float(k.get("t", 0.0)))
    holders = sorted({str(k["holder_id"]) for k in keys if k.get("holder_id") in hands})
    constraints = {h: add_hold_constraint(root, hands[h]) for h in holders}
    for key in keys:
        key_prop(root, [o for o, _ in built], constraints, key, fps)
    for obj, _ in built:
        set_constant(obj, "hide_render")
    for con in constraints.values():
        set_constant(root, f'constraints["{con.name}"].influence')
    return built


def key_prop(
    root: Obj, meshes: list[Obj], constraints: dict[str, Any], key: Json, fps: int
) -> None:
    """One prop key: location, visibility (on every mesh) and hold-constraint influences."""
    frame = frame_at(float(key.get("t", 0.0)), fps)
    root.location = vec(key.get("position"))
    root.keyframe_insert("location", frame=frame)
    hidden = not bool(key.get("visible", True))
    for obj in meshes:
        obj.hide_render = hidden
        obj.keyframe_insert("hide_render", frame=frame)
    for holder, con in constraints.items():
        con.influence = 1.0 if key.get("holder_id") == holder else 0.0
        con.keyframe_insert("influence", frame=frame)


def add_hold_constraint(obj: Obj, hand: Obj) -> Any:
    """World-space Copy Location to a hand node (influence keyed 0/1 per prop key)."""
    con = obj.constraints.new("COPY_LOCATION")
    con.name = f"hold_{hand.name}"
    con.target = hand
    con.influence = 0.0
    return con

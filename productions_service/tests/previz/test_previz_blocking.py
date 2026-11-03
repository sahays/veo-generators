"""Previz blocking + camera: plan x through the master camera, bounded motion, props, rigs,
shot cameras in the master family, plate projection and push poses."""

from __future__ import annotations

import itertools
import math

import pytest

from storygraph.keyframes.plan.models import (
    BeatSpan,
    CameraInput,
    CastInput,
    KeyframePlan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.motion import MAX_STEP_X
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.previz.blocking.poses import body_pose
from storygraph.previz.blocking.project import camera_from_rig, master_camera, to_image
from storygraph.previz.blocking.tracks import MAX_STEP_Y, blocking_track
from storygraph.previz.camera.rig import camera_rig
from storygraph.previz.layout.estimate import (
    LayoutObs,
    LayoutRequest,
    PieceObs,
    build_layout,
)
from storygraph.previz.scene import build_previz_scene
from storygraph.schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    LocationLayout,
    Vec3,
)

_ROOM = "loc_ws"
_BENCH = ObjectInput(entity_id="obj_bench", name="Workbench")


def _snap(order: int, ava_holding: str = "") -> StateSnapshot:
    states = {
        "char_a": {"location": _ROOM}
        | ({"holding": ava_holding} if ava_holding else {}),
        "char_b": {"location": _ROOM},
        "obj_bench": {"location": _ROOM},
        "obj_key": {"location": _ROOM}
        | ({} if ava_holding else {"supported_by": "obj_bench"}),
        "obj_coin": {"location": _ROOM, "sub_location": "hidden inside the drawer"},
    }
    return StateSnapshot(order=order, states=states)


def _input() -> PlanInput:
    """Ava walks to the bench (1..4 s) then takes the key lying on it (5..7 s); Pip watches."""
    return PlanInput(
        project_id="p",
        scene_id="scn",
        shot_id="shot_1",
        clip_index=1,
        duration_s=9.0,
        location_id=_ROOM,
        location_name="Workshop",
        cast=[
            CastInput(
                entity_id="char_a", name="Ava", wardrobe="jacket", position="left"
            ),
            CastInput(
                entity_id="char_b",
                name="Pip",
                wardrobe="",
                description="small robot",
                position="right",
            ),
        ],
        objects=[
            _BENCH,
            ObjectInput(entity_id="obj_key", name="Brass Key"),
            ObjectInput(entity_id="obj_coin", name="Coin"),
        ],
        beats=[
            BeatSpan(
                index=0,
                t_start=1,
                t_end=4,
                actor_id="char_a",
                target_id="obj_bench",
                action="Ava walks to the workbench.",
            ),
            BeatSpan(
                index=1,
                t_start=5,
                t_end=7,
                actor_id="char_a",
                target_id="obj_key",
                action="Ava takes the brass key.",
            ),
        ],
        snapshots=[_snap(0), _snap(1), _snap(2, "obj_key")],
        layout={"obj_bench": 0.7},
    )


def _layout(master: CameraRig | None = None) -> LocationLayout:
    req = LayoutRequest(
        location_id=_ROOM,
        name="Workshop",
        plate_layout_x={"obj_bench": 0.7},
        set_pieces=(_BENCH,),
        master=master,
    )
    obs = LayoutObs(pieces=[PieceObs(name="Workbench", depth=0.8)])
    return build_layout(req, obs)


def _setup() -> tuple[PlanInput, KeyframePlan, LocationLayout, BlockingTrack]:
    inp = _input()
    plan = plan_keyframes(inp)
    layout = _layout()
    return inp, plan, layout, blocking_track(inp, plan, layout, {"char_a": "#ffcc00"})


def test_character_positions_reproject_to_plan_x_with_bounded_steps() -> None:
    inp, plan, layout, track = _setup()
    cam = master_camera(layout.room)
    max_step = (
        2 * MAX_STEP_X * (layout.room.depth - cam.position.y) * cam.tan_h + MAX_STEP_Y
    )
    for char in track.characters:
        plan_x = [
            next(c.x for c in k.characters if c.entity_id == char.entity_id)
            for k in plan.keyframes
        ]
        assert len(char.keys) == len(plan.keyframes)
        for key, x in zip(char.keys, plan_x, strict=True):
            p = Vec3(x=key.position.x, y=key.position.y, z=char.height_m / 2)
            assert to_image(cam, p)[0] == pytest.approx(x, abs=0.01)
        for a, b in itertools.pairwise(char.keys):
            assert (
                math.hypot(b.position.x - a.position.x, b.position.y - a.position.y)
                <= max_step
            )
    bodies = {c.entity_id: (c.archetype, c.height_m) for c in track.characters}
    assert bodies == {"char_a": ("human", 1.72), "char_b": ("small_robot", 0.9)}


def test_actor_walks_facing_motion_and_ends_in_front_of_the_bench() -> None:
    _, _, layout, track = _setup()
    ava = next(c for c in track.characters if c.entity_id == "char_a")
    walking = [
        (a, b)
        for a, b in itertools.pairwise(ava.keys)
        if b.position.x - a.position.x > 0.05
    ]
    assert walking, "Ava must cross towards the bench"
    for a, _ in walking:
        assert a.pose == "walk" and 0.0 < a.facing_deg < 180.0  # heading screen-right
    bench = layout.set_pieces[0]
    front = bench.position.y - bench.size.y / 2
    assert front - 0.6 < ava.keys[-1].position.y < front  # stepped up to the bench
    pip = next(c for c in track.characters if c.entity_id == "char_b")
    assert {k.pose for k in pip.keys} == {"stand"}
    assert any(k.pose == "reach" for k in ava.keys)  # "midway: Ava takes the brass key"


def test_props_follow_holder_hide_and_never_duplicate() -> None:
    _, plan, layout, track = _setup()
    assert sorted(p.entity_id for p in track.props) == [
        "obj_coin",
        "obj_key",
    ]  # bench is set
    assert all(
        [k.t for k in p.keys] == [float(f.t) for f in plan.keyframes]
        for p in track.props
    )
    coin = next(p for p in track.props if p.entity_id == "obj_coin")
    assert not any(k.visible for k in coin.keys)
    key = next(p for p in track.props if p.entity_id == "obj_key")
    ava = {
        k.t: k
        for k in next(c for c in track.characters if c.entity_id == "char_a").keys
    }
    bench = layout.set_pieces[0]
    first = key.keys[0]
    assert first.holder_id is None and first.position.z == pytest.approx(
        bench.size.z + key.size.z / 2
    )
    assert abs(first.position.x - bench.position.x) < bench.size.x / 2
    held = [k for k in key.keys if k.holder_id]
    assert held and all(k.holder_id == "char_a" for k in held)
    for k in held:
        hand = ava[k.t].position
        assert math.hypot(k.position.x - hand.x, k.position.y - hand.y) < 0.6


def _pitch(pos: Vec3, tgt: Vec3) -> float:
    return math.degrees(
        math.atan2(tgt.z - pos.z, math.hypot(tgt.x - pos.x, tgt.y - pos.y))
    )


def test_camera_rig_sizes_angles_and_moves() -> None:
    layout = _layout()
    cam = master_camera(layout.room)
    ws = camera_rig(layout, CameraInput(shot_size="WS"), None, 8.0)
    assert (ws.position, ws.target, ws.end_position) == (cam.position, cam.target, None)
    focus = Vec3(x=1.0, y=3.0, z=1.6)
    mcu = camera_rig(layout, CameraInput(shot_size="MCU"), focus, 8.0)
    assert math.dist(
        (mcu.position.x, mcu.position.y, mcu.position.z),
        (mcu.target.x, mcu.target.y, mcu.target.z),
    ) == pytest.approx(1.8, abs=1e-2)
    assert mcu.target.z == pytest.approx(0.82 * 1.6, abs=1e-3)
    low = camera_rig(layout, CameraInput(shot_size="MS", angle="low"), focus, 8.0)
    assert low.position.z < low.target.z
    dolly = camera_rig(
        layout, CameraInput(shot_size="MS", movement="dolly in"), focus, 2.0
    )
    assert dolly.end_position is not None and dolly.end_target == dolly.target
    closer = math.dist(
        (dolly.position.x, dolly.position.y), (dolly.target.x, dolly.target.y)
    ) - math.dist(
        (dolly.end_position.x, dolly.end_position.y), (dolly.target.x, dolly.target.y)
    )
    assert closer == pytest.approx(0.7, abs=1e-3)  # 0.35 m/s × 2 s (< 40 % of 3 m)
    pan = camera_rig(layout, CameraInput(shot_size="WS", movement="pan_l"), None, 4.0)
    assert pan.end_position == pan.position and pan.end_target is not None
    assert pan.end_target.x < pan.target.x


_CALIBRATED = CameraRig(
    position=Vec3(x=-1.0, y=-2.0, z=2.2),
    target=Vec3(x=0.5, y=3.5, z=0.6),
    lens_mm=28.0,
    sensor_width_mm=36.0,
    shift_y=0.04,
)


def test_closer_shots_stay_in_the_calibrated_master_family() -> None:
    layout, focus = _layout(), Vec3(x=0.8, y=3.2, z=1.7)
    ws = camera_rig(layout, CameraInput(shot_size="WS"), None, 4.0, master=_CALIBRATED)
    assert ws == _CALIBRATED  # WS is the plate camera itself (lens, sensor, shift)
    for size in ("MLS", "MS", "MCU", "CU"):
        rig = camera_rig(
            layout, CameraInput(shot_size=size), focus, 4.0, master=_CALIBRATED
        )
        to_master = _pitch(rig.target, _CALIBRATED.position)
        assert -_pitch(rig.position, rig.target) == pytest.approx(to_master, abs=0.5)
        yaw = math.atan2(rig.target.x - rig.position.x, rig.target.y - rig.position.y)
        want = math.atan2(
            rig.target.x - _CALIBRATED.position.x, rig.target.y - _CALIBRATED.position.y
        )
        assert yaw == pytest.approx(want, abs=1e-2)  # on the master's line of sight
        assert (rig.sensor_width_mm, rig.shift_y) == (36.0, 0.0)


def test_previz_scene_matches_aspect_and_is_deterministic() -> None:
    inp, plan, layout, _ = _setup()
    wide = build_previz_scene(inp, plan, layout, {}, "16:9", fps=24)
    tall = build_previz_scene(inp, plan, layout, {}, "9:16", fps=12)
    assert (wide.render.width, wide.render.height) == (480, 270)
    assert (tall.render.width, tall.render.height, tall.render.fps) == (270, 480, 12)
    assert (
        wide.model_dump_json()
        == build_previz_scene(inp, plan, layout, {}).model_dump_json()
    )


def test_scene_projects_the_plate_only_when_one_exists() -> None:
    inp, plan, layout, _ = _setup()
    bare = build_previz_scene(inp, plan, layout, {})
    assert bare.projection is None
    assert (bare.render.passes, bare.render.pass_fps) == (["object_id", "depth"], 1)
    plated = build_previz_scene(
        inp, plan, layout, {}, master=_CALIBRATED, has_plate=True
    )
    assert plated.projection is not None
    assert plated.projection.image_file == "plate.png"
    assert plated.projection.camera == _CALIBRATED
    synthetic = build_previz_scene(inp, plan, layout, {}, has_plate=True)
    assert synthetic.projection is not None
    assert synthetic.projection.camera.position == master_camera(layout.room).position
    assert synthetic.projection.camera.lens_mm == 35.0


def test_blocking_projects_through_the_calibrated_master() -> None:
    inp, plan, _, _ = _setup()
    layout = _layout(_CALIBRATED)  # the layout is estimated through the same camera
    bench = layout.set_pieces[0]
    centre = Vec3(x=bench.position.x, y=bench.position.y, z=bench.size.z / 2)
    assert to_image(camera_from_rig(_CALIBRATED), centre)[0] == pytest.approx(
        0.7, abs=0.01
    )
    track = blocking_track(inp, plan, layout, {}, master=_CALIBRATED)
    cam = camera_from_rig(_CALIBRATED)
    pip = next(c for c in track.characters if c.entity_id == "char_b")
    for key, frame in zip(pip.keys, plan.keyframes, strict=True):
        x = next(c.x for c in frame.characters if c.entity_id == "char_b")
        p = Vec3(x=key.position.x, y=key.position.y, z=pip.height_m / 2)
        assert to_image(cam, p)[0] == pytest.approx(x, abs=0.01)


@pytest.mark.parametrize(
    ("text", "moving", "contact", "pose"),
    [
        ("midway: Ava pushes the cabinet", False, False, "push"),
        ("midway: Ava closes the drawer", False, False, "push"),
        ("midway: Ava heaves the crate aside", True, True, "push"),
        ("starting: Ava shoves the cart", True, False, "walk"),  # walking up to it
        ("midway: Ava walks closer", False, False, "stand"),  # "closer" is not "close"
        ("about to: Ava pushes the cabinet", False, False, "stand"),
        ("midway: Ava takes the key", False, False, "reach"),
    ],
)
def test_push_pose_rules(text: str, moving: bool, contact: bool, pose: str) -> None:
    assert body_pose(text, moving, contact) == pose

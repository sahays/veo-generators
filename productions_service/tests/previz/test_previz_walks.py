"""Beat walks: actors walk to props they act on and walk in when they enter (plan x static)."""

from __future__ import annotations

import itertools
import math

from storygraph.keyframes.plan.models import (
    BeatSpan,
    CastInput,
    KeyframePlan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.previz.blocking.stage import WALL_PAD, build_stage
from storygraph.previz.blocking.tracks import blocking_track
from storygraph.previz.blocking.walks import ARRIVE_FRAC, WALK_SPEED, stand_point
from storygraph.previz.layout.estimate import (
    LayoutObs,
    LayoutRequest,
    PieceObs,
    build_layout,
)
from storygraph.schemas.previz_scene import CharacterTrack, LocationLayout

_ROOM = "loc_ws"
_BENCH = ObjectInput(entity_id="obj_bench", name="Workbench")
_CABINET = ObjectInput(entity_id="obj_cabinet", name="Blue Cabinet")


def _layout() -> LocationLayout:
    req = LayoutRequest(
        location_id=_ROOM,
        name="Workshop",
        plate_layout_x={"obj_bench": 0.75},
        set_pieces=(_BENCH,),
    )
    obs = LayoutObs(pieces=[PieceObs(name="Workbench", depth=0.8)])
    return build_layout(req, obs)


def _input(action: str, target: str, position: str = "left") -> PlanInput:
    states = {
        "char_p": {"location": _ROOM},
        "obj_bench": {"location": _ROOM},
        "obj_cabinet": {"location": _ROOM},
    }
    snap = StateSnapshot(order=0, states=states)
    return PlanInput(
        project_id="p",
        scene_id="scn",
        shot_id="shot_w",
        clip_index=1,
        duration_s=9.0,
        location_id=_ROOM,
        location_name="Workshop",
        cast=[
            CastInput(entity_id="char_p", name="Pip", wardrobe="", position=position)
        ],
        objects=[_BENCH, _CABINET],
        beats=[
            BeatSpan(
                index=0,
                t_start=2,
                t_end=6,
                actor_id="char_p",
                target_id=target,
                action=action,
            )
        ],
        snapshots=[snap, snap],
        layout={"obj_bench": 0.75},
    )


def _track(inp: PlanInput) -> tuple[KeyframePlan, CharacterTrack]:
    plan = plan_keyframes(inp)
    return plan, blocking_track(inp, plan, _layout(), {}).characters[0]


def test_actor_walks_to_a_prop_the_plan_cannot_place() -> None:
    inp = _input("Pip pushes the cabinet drawer shut.", "obj_cabinet")
    plan, pip = _track(inp)
    xs = {round(next(c.x for c in k.characters), 3) for k in plan.keyframes}
    assert len(xs) == 1  # the 2D plan keeps Pip still: the cabinet has no plate x
    keys = pip.keys
    start = (keys[2].position.x, keys[2].position.y)
    dest = stand_point(
        build_stage(inp, _layout(), "16:9"), inp, plan, inp.beats[0], start
    )
    assert dest is not None and math.dist(start, dest) > 0.5
    assert all(
        (k.position.x, k.position.y) == start for k in keys[:3]
    )  # leaves at t_start
    for a, b in itertools.pairwise(keys):
        assert (
            math.dist((a.position.x, a.position.y), (b.position.x, b.position.y))
            <= WALK_SPEED + 1e-6
        )
    arrived = [k for k in keys if math.dist((k.position.x, k.position.y), dest) < 0.1]
    assert arrived and arrived[0].t <= max(
        math.ceil(2 + ARRIVE_FRAC * 4),
        2 + math.ceil(math.dist(start, dest) / WALK_SPEED),
    )
    moving = [a for a, b in itertools.pairwise(keys) if a.position != b.position]
    assert moving and all(k.pose == "walk" for k in moving)
    assert any(k.pose == "reach" and k.t <= 6 for k in arrived)


def test_entering_actor_starts_at_the_side_wall_and_walks_in() -> None:
    layout = _layout()
    inp = _input(
        "Pip enters and walks to the workbench.", "obj_bench", position="right"
    )
    _, pip = _track(inp)
    edge = layout.room.width / 2 - WALL_PAD
    first = pip.keys[0].position
    assert abs(abs(first.x) - edge) < 1e-6  # off at the side wall before the beat
    assert all(k.position == first for k in pip.keys[:3])
    bench = layout.set_pieces[0]
    last = pip.keys[-1].position
    assert abs(last.x - bench.position.x) <= bench.size.x / 2
    assert last.y < bench.position.y  # standing in front of the bench
    assert any(k.pose == "walk" for k in pip.keys[2:6])

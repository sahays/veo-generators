"""1 fps keyframe planner: per-second graph state, object invariants, wardrobe, timeline."""

from __future__ import annotations

import pytest
from conftest import seed_valid_graph

from storygraph.keyframes.plan.graph_source import build_plan_input
from storygraph.keyframes.plan.lint import lint_plan, lint_scene
from storygraph.keyframes.plan.models import (
    BeatSpan,
    CastInput,
    KeyframePlan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.permanence import backfill_established
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.repo import Repo
from storygraph.timeline.clip_events import scene_clip_windows

_ROOM = "loc_room"


def _snap(order: int, key: dict[str, str], holders: dict[str, str]) -> StateSnapshot:
    states: dict[str, dict[str, str]] = {
        "char_a": {"location": _ROOM},
        "char_b": {"location": _ROOM},
        "obj_table": {"location": _ROOM},
        "obj_cabinet": {"location": _ROOM, "sub_location": "bottom drawer closed"},
        "obj_cloth": {
            "location": _ROOM,
            "supported_by": "obj_cabinet",
            "sub_location": "lower drawer",
        },
        "obj_key": {"location": _ROOM, **key},
    }
    for who, what in holders.items():
        states[who]["holding"] = what
    return StateSnapshot(order=order, states=states)


def _input() -> PlanInput:
    """A hands the key to B (0-4.5s), B sets it on the table (4.5-9s)."""
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
                entity_id="char_a",
                name="Ava",
                wardrobe="yellow jacket",
                position="left",
            ),
            CastInput(
                entity_id="char_b",
                name="Pip",
                wardrobe="teal chassis",
                position="right",
            ),
        ],
        objects=[
            ObjectInput(entity_id=o, name=n, focus=o == "obj_key")
            for o, n in [
                ("obj_key", "Brass Key"),
                ("obj_table", "Table"),
                ("obj_cabinet", "Blue Cabinet"),
                ("obj_cloth", "Green Cloth"),
            ]
        ],
        beats=[
            BeatSpan(
                index=0,
                t_start=0.0,
                t_end=4.5,
                actor_id="char_a",
                target_id="char_b",
                action="Ava hands the brass key to Pip.",
            ),
            BeatSpan(
                index=1,
                t_start=4.5,
                t_end=9.0,
                actor_id="char_b",
                target_id="obj_key",
                action="Pip sets the brass key on the table.",
            ),
        ],
        snapshots=[
            _snap(10, {}, {"char_a": "obj_key"}),
            _snap(11, {}, {"char_b": "obj_key"}),
            _snap(12, {"supported_by": "obj_table"}, {}),
        ],
    )


def _holder(plan: KeyframePlan, t: int) -> str | None:
    return next(o.holder_id for o in plan.at(t).objects if o.entity_id == "obj_key")


def test_one_keyframe_per_second_follows_graph_handoffs() -> None:
    plan = plan_keyframes(_input())
    assert [k.t for k in plan.keyframes] == list(range(10))
    # Hand-offs switch at the beat midpoint (2.25s, 6.75s), never earlier or later.
    assert [_holder(plan, t) for t in (0, 2, 3, 6, 7, 9)] == [
        "char_a",
        "char_a",
        "char_b",
        "char_b",
        None,
        None,
    ]
    placed = next(o for o in plan.at(9).objects if o.entity_id == "obj_key")
    assert placed.placement == "on the Table"
    assert plan.at(3).delta and "Pip now holds Brass Key" in plan.at(3).delta


def test_every_object_exactly_once_and_constant_set() -> None:
    plan = plan_keyframes(_input())
    for frame in plan.keyframes:
        ids = [o.entity_id for o in frame.objects]
        assert sorted(ids) == ["obj_cabinet", "obj_cloth", "obj_key", "obj_table"]
    assert lint_plan(plan, _input()) == []


def test_contained_objects_hidden_but_container_visible() -> None:
    frame = plan_keyframes(_input()).at(0)
    vis = {o.entity_id: o.visible for o in frame.objects}
    assert vis["obj_cabinet"] is True  # its own drawer state does not hide it
    assert vis["obj_cloth"] is False  # inside the cabinet drawer


def test_held_object_behind_back_hidden_unless_beat_acts_on_it() -> None:
    inp = _input()
    inp.snapshots[0].states["char_a"]["sub_location"] = "key hidden behind back"
    inp.beats[0] = inp.beats[0].model_copy(
        update={"action": "Ava waits.", "target_id": None}
    )
    hidden = plan_keyframes(inp).at(0)
    assert not next(o.visible for o in hidden.objects if o.entity_id == "obj_key")
    exposed = plan_keyframes(
        _input().model_copy(update={"snapshots": inp.snapshots})
    ).at(0)
    assert next(o.visible for o in exposed.objects if o.entity_id == "obj_key")


def test_wardrobe_constant_and_scene_handoff_clean() -> None:
    first = plan_keyframes(_input())
    end_x = {c.entity_id: c.x for c in first.keyframes[-1].characters}
    second_inp = _input().model_copy(
        update={"shot_id": "shot_2", "clip_index": 2, "start_x": end_x}
    )
    second_inp.snapshots = [_input().snapshots[-1]] * 3
    second = plan_keyframes(second_inp)
    assert {
        c.wardrobe
        for k in first.keyframes
        for c in k.characters
        if c.entity_id == "char_a"
    } == {"yellow jacket"}
    assert lint_scene([first, second]) == []


def test_lint_flags_duplicates_vanishing_wardrobe_jumps_and_timeline() -> None:
    inp = _input()
    plan = plan_keyframes(inp)
    frames = [k.model_copy(deep=True) for k in plan.keyframes]
    frames[2].objects.append(frames[2].objects[0])  # duplicate chest-style drift
    frames[5].objects = [o for o in frames[5].objects if o.entity_id != "obj_cabinet"]
    frames[6].characters[0].wardrobe = "red coat"
    frames[7].characters[0].x = frames[6].characters[0].x + 0.68  # teleport
    frames[9].objects[0].holder_id = "char_a"
    bad = plan.model_copy(update={"keyframes": frames})
    issues = lint_plan(bad, inp)
    codes = {i.code for i in issues}
    jumps = {(i.t, i.entity_id) for i in issues if i.code == "position_jump"}
    assert (7, "char_a") in jumps and all(eid == "char_a" for _, eid in jumps)
    assert codes >= {
        "object_duplicate",
        "object_count",
        "wardrobe_change",
        "position_jump",
        "timeline_close",
    }


def test_backfill_keeps_set_pieces_but_not_carried_in_props() -> None:
    snaps = [
        StateSnapshot(order=1, states={"char_a": {"holding": "obj_box"}}),
        StateSnapshot(
            order=2,
            states={
                "obj_chest": {"location": _ROOM},
                "obj_box": {"location": _ROOM},
                "char_a": {"holding": "obj_box"},
            },
        ),
    ]
    out = backfill_established(snaps, ["obj_chest", "obj_box"], _ROOM)
    assert out[0].states["obj_chest"]["location"] == _ROOM
    assert "obj_box" not in out[0].states
    assert "obj_chest" not in snaps[0].states  # input untouched


@pytest.mark.parametrize("duration", [8.0, 9.0, 10.0])
def test_graph_source_matches_clip_window(tmp_repo: Repo, duration: float) -> None:
    shot = seed_valid_graph(tmp_repo)
    scene = tmp_repo.get_scene(shot.scene_id)
    assert scene is not None
    clips = [c.model_copy(update={"duration_s": duration}) for c in scene.clips]
    scene = tmp_repo.put_scene(scene.model_copy(update={"clips": clips}))
    inp = build_plan_input(tmp_repo, scene, shot)
    win = scene_clip_windows(scene, tmp_repo.list_events(scene_id=scene.id))[1]
    assert (inp.snapshots[0].order, inp.snapshots[-1].order) == (
        win.open_at,
        win.close_at,
    )
    plan = plan_keyframes(inp)
    assert len(plan.keyframes) == round(duration) + 1
    assert plan.keyframes[-1].snapshot_index == len(inp.snapshots) - 1
    assert inp.beats[-1].t_end == duration
    assert lint_plan(plan, inp) == []

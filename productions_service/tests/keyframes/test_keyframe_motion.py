"""Plate-anchored motion: beat anchors, bounded per-second displacement, clip carry-over."""

from __future__ import annotations

import itertools

import pytest

from storygraph.keyframes.plan.lint import lint_plan, lint_scene
from storygraph.keyframes.plan.models import (
    BeatSpan,
    CastInput,
    KeyframePlan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.motion import MAX_STEP_X, rate_limit
from storygraph.keyframes.plan.planner import plan_keyframes

_ROOM = "loc_room"
_STATES = {
    "char_a": {"location": _ROOM},
    "char_b": {"location": _ROOM},
    "obj_table": {"location": _ROOM},
}


def _input(layout: dict[str, float] | None = None) -> PlanInput:
    """Ava (left, x=0.22) walks to the table during 3..4 s; Pip (right) stays put."""
    snap = StateSnapshot(order=1, states={k: dict(v) for k, v in _STATES.items()})
    return PlanInput(
        project_id="p",
        scene_id="scn",
        shot_id="shot_1",
        clip_index=1,
        duration_s=8.0,
        location_id=_ROOM,
        location_name="Workshop",
        cast=[
            CastInput(
                entity_id="char_a", name="Ava", wardrobe="yellow", position="left"
            ),
            CastInput(
                entity_id="char_b", name="Pip", wardrobe="teal", position="right"
            ),
        ],
        objects=[ObjectInput(entity_id="obj_table", name="Table")],
        beats=[
            BeatSpan(
                index=0,
                t_start=3.0,
                t_end=4.0,
                actor_id="char_a",
                target_id="obj_table",
                action="Ava walks to the table.",
            )
        ],
        snapshots=[snap, snap.model_copy(update={"order": 2})],
        layout={"obj_table": 0.5} if layout is None else layout,
    )


def _xs(plan: KeyframePlan, cid: str) -> list[float]:
    return [
        next(c.x for c in k.characters if c.entity_id == cid) for k in plan.keyframes
    ]


def test_rate_limit_turns_a_teleport_into_bounded_steps() -> None:
    assert rate_limit([0.1, 0.9, 0.9, 0.9, 0.9, 0.9]) == [
        0.1,
        0.28,
        0.46,
        0.64,
        0.82,
        0.9,
    ]
    assert rate_limit([0.9, 0.1, 0.1]) == [0.9, 0.72, 0.54]


def test_actor_holds_until_beat_then_walks_beside_target_within_step() -> None:
    plan = plan_keyframes(_input())
    ava = _xs(plan, "char_a")
    assert ava[:4] == [0.22] * 4  # holds through the beat's t_start (3 s)
    assert all(abs(b - a) <= MAX_STEP_X + 1e-9 for a, b in itertools.pairwise(ava))
    assert ava[4] == pytest.approx(0.22 + MAX_STEP_X)  # 0.20 needed: rate-limited
    assert ava[-1] == pytest.approx(0.42)  # beside the table (0.5 - gap), from the left
    assert set(_xs(plan, "char_b")) == {0.78}  # bystander never moves
    table = next(o for o in plan.at(0).objects if o.entity_id == "obj_table")
    assert table.x == 0.5
    assert any(d.startswith("Ava moves to x=0.40") for d in plan.at(4).delta)
    assert lint_plan(plan, _input()) == []


def test_start_x_carries_over_so_scene_handoff_is_clean() -> None:
    first = plan_keyframes(_input())
    last = {c.entity_id: c.x for c in first.keyframes[-1].characters}
    base = _input().model_copy(
        update={"shot_id": "shot_2", "clip_index": 2, "beats": []}
    )
    carried = plan_keyframes(base.model_copy(update={"start_x": last}))
    assert _xs(carried, "char_a")[0] == last["char_a"]
    assert lint_scene([first, carried]) == []
    fresh = plan_keyframes(base)  # without carry-over Ava would snap back to x=0.22
    assert [i.entity_id for i in lint_scene([first, fresh])] == ["char_a"]


def test_plan_hash_changes_with_layout() -> None:
    same = plan_keyframes(_input()).plan_hash
    assert plan_keyframes(_input()).plan_hash == same
    assert plan_keyframes(_input({"obj_table": 0.7})).plan_hash != same

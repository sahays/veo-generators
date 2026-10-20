"""Deterministic clip partition / split / dialogue re-balance (pure functions)."""

from __future__ import annotations

from storygraph.clips.limits import CLIP_LIMITS
from storygraph.clips.models import ClipScript
from storygraph.clips.partition import min_groups_from, partition_steps
from storygraph.clips.rebalance import move_overflow_lines, split_clip
from storygraph.clips.text import DialogueRef, StepRef


def _step(i: int, action: str, key: bool) -> StepRef:
    return StepRef(i, "Pip", action, f"pre{i}", f"post{i}", key_action=key)


def _line(lid: str, words: int, text: str = "") -> DialogueRef:
    return DialogueRef(lid, "Pip", text or " ".join(f"{lid}w{n}" for n in range(words)))


def test_partition_never_exceeds_key_action_cap_and_stays_contiguous() -> None:
    keys = [True, True, True, False, True, True]
    groups = partition_steps(keys, 1)
    assert [i for g in groups for i in g] == list(range(len(keys)))
    assert all(sum(keys[i] for i in g) <= CLIP_LIMITS.max_key_actions for g in groups)
    assert all(len(g) <= CLIP_LIMITS.max_clip_steps for g in groups)
    assert len(groups) == min_groups_from(keys)[0] == 3


def test_partition_balances_when_more_groups_are_requested() -> None:
    assert [len(g) for g in partition_steps([False] * 6, 3)] == [2, 2, 2]
    assert [len(g) for g in partition_steps([False] * 2, 5)] == [1, 1]


def test_split_assigns_dialogue_to_the_clip_holding_its_step() -> None:
    """Live scn_002 clip 1: walk+grasp, shove, trot (3 key actions)."""
    steps = {
        1: _step(1, "walks to the chair and grasps it", True),
        2: _step(2, "shoves the chair across the floor", True),
        3: _step(3, "Milo trots into the path", True),
    }
    early, late = _line("d1", 4, "Oof heavy chair"), _line("d2", 3, "Move Milo please")
    prompt = (
        'Pip walks to the chair. Pip says: "Oof heavy chair". Then he shoves it. '
        'Finally Milo trots into the path. Pip says: "Move Milo please".'
    )
    clips = [
        ClipScript(clip_index=1, step_indices=[1, 2, 3], dialogue_line_ids=["d1", "d2"],
                   omni_prompt=prompt, duration_s=9.0),
        ClipScript(clip_index=2, step_indices=[4], omni_prompt="Pip sits.", duration_s=8.0),
    ]  # fmt: skip
    steps[4] = _step(4, "sits", False)
    edit = split_clip(clips, 1, steps, {"d1": early, "d2": late})
    assert edit is not None
    assert [c.step_indices for c in edit.clips] == [[1, 2], [3], [4]]
    assert [c.dialogue_line_ids for c in edit.clips] == [["d1"], ["d2"], []]
    assert edit.origin == {1: 1, 2: None, 3: 2}
    assert all(
        CLIP_LIMITS.min_duration_s <= c.duration_s <= CLIP_LIMITS.max_duration_s
        for c in edit.clips
    )
    assert edit.clips[1].opening_state == edit.clips[0].closing_state == "post2"


def test_overflow_lines_move_to_a_neighbour_with_room_else_none() -> None:
    steps = {i: _step(i, f"acts {i}", False) for i in (1, 2, 3)}
    lines = {"a": _line("a", 12), "b": _line("b", 12), "c": _line("c", 15)}
    clips = [
        ClipScript(clip_index=1, step_indices=[1], dialogue_line_ids=[]),
        ClipScript(clip_index=2, step_indices=[2], dialogue_line_ids=["a", "b"]),
        ClipScript(clip_index=3, step_indices=[3], dialogue_line_ids=["c"]),
    ]
    edit = move_overflow_lines(clips, 2, steps, lines)
    assert edit is not None
    assert [c.dialogue_line_ids for c in edit.clips] == [["a"], ["b"], ["c"]]
    full = [clips[0].model_copy(update={"dialogue_line_ids": ["c"]}), clips[1]]
    lines["c"] = _line("c", 19)
    assert move_overflow_lines(full, 2, steps, lines) is None

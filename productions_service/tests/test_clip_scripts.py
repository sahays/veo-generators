"""Clip-script contract tests: partition rules, Omni prompt compilation, director 1:1 mapping, fallback validity."""

from __future__ import annotations

import re

import pytest
from conftest import seed_valid_graph
from storygraph.agents.role.director import run_director_for_scene
from storygraph.agents.role.screenwriter import run_screenwriter_for_scene
from storygraph.budget import select_references
from storygraph.clips.builder import build_clips, finalize_clips
from storygraph.clips.models import ClipScript, ColorGradeSpec, LightingSpec, ShotLook
from storygraph.clips.text import DialogueRef, StepRef, has_timestamps
from storygraph.clips.validation import (
    CODE_GAP,
    CODE_OUT_OF_RANGE,
    CODE_OVERLAP,
    validate_partition,
)
from storygraph.compile import compile_shot
from storygraph.omni.spec import OmniClipSpec
from storygraph.config import Config
from storygraph.errors import ValidationFailed
from storygraph.repo import Repo
from storygraph.schema import InteractionStep, Role
from storygraph.tools.registry import ToolContext
from storygraph.validate import validate_all
from storygraph.views import shot_view

_RANGE_RE = re.compile(r"\d+(?:\.\d+)?\s*[–-]\s*\d+(?:\.\d+)?\s*s\b")


def _clip(idx: int, steps: list[int]) -> ClipScript:
    return ClipScript(clip_index=idx, omni_prompt="x", step_indices=steps)


@pytest.mark.parametrize(
    ("clip_steps", "expected"),
    [
        ([[1, 2], [4]], CODE_GAP),
        ([[1, 2], [2, 3, 4]], CODE_OVERLAP),
        ([[1, 2], [3, 4, 9]], CODE_OUT_OF_RANGE),
    ],
)
def test_partition_catches_gap_overlap_out_of_range(
    clip_steps: list[list[int]], expected: str
) -> None:
    clips = [_clip(i, s) for i, s in enumerate(clip_steps, start=1)]
    codes = {i.code for i in validate_partition("scn", [1, 2, 3, 4], clips)}
    assert expected in codes
    assert (
        validate_partition("scn", [1, 2, 3, 4], [_clip(1, [1, 2]), _clip(2, [3, 4])])
        == []
    )


def test_finalize_strips_timestamps_remaps_dialogue_and_chains_states() -> None:
    steps = [StepRef(i, "Mira", f"step {i}", f"pre{i}", f"post{i}") for i in (1, 2, 3)]
    lines = [DialogueRef("dlg_s_01", "Mira", "We leave at dawn.")]
    raw = [
        ClipScript(
            clip_index=7,
            duration_s=12,
            omni_prompt="(0.0–3.5s) Mira packs.",
            step_indices=[1, 2],
            dialogue_line_ids=["L1"],
            closing_state="bag packed",
        ),
        ClipScript(
            clip_index=9,
            duration_s=3,
            omni_prompt="Then Mira leaves at 4s.",
            step_indices=[3],
            opening_state="different",
        ),
    ]
    clips = finalize_clips("s", raw, steps, lines, {"L1": "dlg_s_01"})
    assert [c.clip_index for c in clips] == [1, 2]
    assert [c.duration_s for c in clips] == [10.0, 8.0]
    assert clips[0].dialogue_line_ids == ["dlg_s_01"]
    assert '"We leave at dawn."' in clips[0].omni_prompt
    assert not any(has_timestamps(c.omni_prompt) for c in clips)
    assert clips[1].opening_state == "bag packed"


def test_build_clips_respects_action_and_word_limits() -> None:
    steps = [StepRef(i, "Ravi", f"does thing {i}", "", "") for i in range(1, 6)]
    long_line = " ".join(["word"] * 15)
    lines = [DialogueRef(f"d{i}", "Ravi", long_line) for i in range(3)]
    clips = build_clips(steps, lines)
    assert [i for c in clips for i in c.step_indices] == [1, 2, 3, 4, 5]
    assert all(len(c.step_indices) <= 3 for c in clips)
    words = {f"d{i}": 15 for i in range(3)}
    assert all(sum(words[d] for d in c.dialogue_line_ids) <= 22 for c in clips)
    assert all(8.0 <= c.duration_s <= 10.0 for c in clips)


def _with_look(repo: Repo) -> None:
    shot = repo.get_shot("shot_1")
    assert shot is not None
    look = ShotLook(
        lighting=LightingSpec(
            key="tungsten desk lamp key", direction="from screen left"
        ),
        color_grade=ColorGradeSpec(shades=["teal shadows"], contrast="high"),
        mood="wary resolve",
        composition="rule of thirds, compass in foreground",
    )
    repo.put_shot(shot.model_copy(update={"look": look}))


def test_compiled_prompt_uses_omni_prompt_verbatim_and_look(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    _with_look(tmp_repo)
    view = shot_view(tmp_repo, "shot_1")
    pkg = compile_shot(view, select_references(view, default_cfg), default_cfg)
    spec = OmniClipSpec.model_validate_json(pkg.compiled_prompt)
    assert spec.summary == view.scene.clips[0].omni_prompt
    assert not _RANGE_RE.search(pkg.compiled_prompt)
    assert spec.look is not None and spec.look.mood == "wary resolve"
    assert "tungsten desk lamp key" in (spec.look.lighting or "")
    assert "teal shadows" in (spec.look.color_grade or "")
    assert "compass in foreground" in (spec.look.composition or "")
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    edited = scene.clips[0].model_copy(
        update={"omni_prompt": "Arjun pockets the compass."}
    )
    tmp_repo.put_scene(scene.model_copy(update={"clips": [edited]}))
    pkg2 = compile_shot(
        shot_view(tmp_repo, "shot_1"), select_references(view, default_cfg), default_cfg
    )
    assert pkg2.package_hash != pkg.package_hash


def test_scene_without_clips_fails_validation_and_compile(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    tmp_repo.put_scene(scene.model_copy(update={"clips": []}))
    codes = {i.code for i in validate_all(tmp_repo, default_cfg)}
    assert "S2_CLIPS_MISSING" in codes
    view = shot_view(tmp_repo, "shot_1")
    with pytest.raises(ValidationFailed):
        compile_shot(view, select_references(view, default_cfg), default_cfg)


def _three_step_scene(repo: Repo) -> None:
    scene = repo.get_scene("scn_1")
    assert scene is not None
    steps = [
        InteractionStep(
            step_index=i,
            actor_id="char_arjun",
            action=f"Arjun moves {i}",
            pre_state=f"p{i}",
            post_state=f"q{i}",
        )
        for i in range(1, 6)
    ]
    repo.put_scene(
        scene.model_copy(
            update={
                "interaction_steps": steps,
                "clips": [
                    ClipScript(
                        clip_index=1,
                        duration_s=9.5,
                        omni_prompt="Arjun moves.",
                        step_indices=[1, 2, 3],
                        dialogue_line_ids=["dlg_1"],
                    ),
                    ClipScript(
                        clip_index=2,
                        duration_s=8.0,
                        omni_prompt="Arjun stops.",
                        step_indices=[4, 5],
                    ),
                ],
            }
        )
    )


def test_director_maps_each_clip_to_one_shot(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    _three_step_scene(tmp_repo)
    ctx = ToolContext(repo=tmp_repo, role=Role.DIRECTOR, cfg=default_cfg)
    run_director_for_scene(ctx, "scn_1")
    shots = sorted(
        tmp_repo.list_shots(scene_id="scn_1"), key=lambda s: s.index_in_scene
    )
    assert [(s.clip_index, s.duration_s) for s in shots] == [(1, 9.5), (2, 8.0)]
    assert shots[0].dialogue_ids == ["dlg_1"] and shots[1].dialogue_ids == []
    assert all(s.look is not None and s.look.lighting.key for s in shots)
    assert shots[0].look.lighting.direction == shots[1].look.lighting.direction  # type: ignore[union-attr]
    assert tmp_repo.get_shot("shot_1") is None  # orphan from previous blocking pruned


def test_fallback_screenwriter_output_passes_clip_validation(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    ctx = ToolContext(repo=tmp_repo, role=Role.SCREENWRITER, cfg=default_cfg)
    run_screenwriter_for_scene(ctx, "scn_1")
    run_director_for_scene(
        ToolContext(repo=tmp_repo, role=Role.DIRECTOR, cfg=default_cfg), "scn_1"
    )
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None and scene.clips
    clip_codes = [
        i.code for i in validate_all(tmp_repo, default_cfg) if "CLIP" in i.code
    ]
    assert clip_codes == []

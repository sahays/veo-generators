"""Spec data on a replay-shaped graph: actor named once, concrete object states, consumed
end states, framing-aware visibility and Omni camera limits."""

from __future__ import annotations

from dataclasses import replace

import pytest
from feed_seed import BERRY, DOOR, PIP, seed_feed
from storygraph.budget import RefPlan
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.lint.models import LintCase
from storygraph.lint.remediate import fix_cameras
from storygraph.lint.spec_lint import lint_shot
from storygraph.lint.text_rules import (
    rule_consumed_end,
    rule_object_state_text,
    rule_repeated_tokens,
)
from storygraph.omni.spec import ObjectSpec, ObjectState, OmniClipSpec
from storygraph.omni.text import strip_actor_lead
from storygraph.repo import Repo
from storygraph.schema import CameraSpec, InteractionStep
from storygraph.timeline.clip_context import clip_context, clip_steps_of
from storygraph.timeline.framing import plan_framing
from storygraph.timeline.placement import cut_phrase, ends_dangling
from storygraph.views import shot_view


def _spec(repo: Repo, cfg: Config, shot_id: str) -> OmniClipSpec:
    pkg = compile_shot(shot_view(repo, shot_id), RefPlan(), cfg)
    return OmniClipSpec.model_validate_json(pkg.spec_json)


def _case(repo: Repo, shot_id: str, spec: OmniClipSpec) -> LintCase:
    view = shot_view(repo, shot_id)
    clip = next(c for c in view.scene.clips if c.clip_index == view.shot.clip_index)
    ctx = clip_context(repo, view.scene, view.shot)
    return LintCase(spec, view, ctx, clip, clip_steps_of(view.scene, clip))


def _obj(spec: OmniClipSpec, name: str) -> ObjectSpec:
    return next(o for o in spec.objects or [] if o.name == name)


def _codes(repo: Repo, cfg: Config, shot_id: str) -> set[str]:
    return {i.code.rsplit("_LINT_", 1)[-1] for i in lint_shot(repo, cfg, shot_id)}


def test_steps_name_the_actor_once(tmp_repo: Repo, default_cfg: Config) -> None:
    seed_feed(tmp_repo)
    spec = _spec(tmp_repo, default_cfg, "shot_9_2")
    rendered = [f"Pip {s.verb}" for s in spec.sequence or []]
    assert rendered[1].startswith("Pip scratches Milo") and "Pip Pip" not in " ".join(
        rendered
    )
    assert not rule_repeated_tokens(_case(tmp_repo, "shot_9_2", spec))
    bad = spec.model_copy(
        update={
            "sequence": [
                s.model_copy(update={"verb": "Pip reaches up"})
                for s in spec.sequence or []
            ]
        }
    )
    assert rule_repeated_tokens(_case(tmp_repo, "shot_9_2", bad))
    # A possessive lead is content, not a repeated actor name.
    assert strip_actor_lead("Pip's sole slips", "Pip") == "Pip's sole slips"


def test_object_states_are_concrete_plain_words(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_feed(tmp_repo)
    spec = _spec(tmp_repo, default_cfg, "shot_9_2")
    door, chair, table = (
        _obj(spec, n) for n in ("Blue Door", "Wooden Chair", "Wooden Dining Table")
    )
    assert door.start.condition == "closed" and door.start.where == "in the Cafe"
    assert chair.start == ObjectState(
        where="beside wooden dining table", condition="jolted"
    )
    assert table.start.where == "in the Cafe"  # was the placeholder 'in_place'
    assert not rule_object_state_text(_case(tmp_repo, "shot_9_2", spec))
    garbled = [
        door.model_copy(update={"start": ObjectState(where="on the closed")}),
        table.model_copy(update={"start": ObjectState(where="in_place")}),
        chair.model_copy(update={"start": ObjectState(where="resting on the")}),
    ]
    flagged = rule_object_state_text(
        _case(tmp_repo, "shot_9_2", spec.model_copy(update={"objects": garbled}))
    )
    assert len(flagged) == 3


@pytest.mark.parametrize("limit", [12, 25, 33, 40])
def test_truncation_cuts_on_phrase_boundaries(limit: int) -> None:
    text = "the bowl rests on the dining table, beside the jug of the morning milk"
    cut = cut_phrase(text, limit)
    assert len(cut) <= limit and text.startswith(cut) and not ends_dangling(cut)


def test_consumed_object_ends_eaten_not_held(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_feed(tmp_repo)
    spec = _spec(tmp_repo, default_cfg, "shot_9_2")
    berry = _obj(spec, "Strawberry")
    assert berry.start.held_by == "S1"
    assert berry.end == ObjectState(where="eaten by Milo")
    case = _case(tmp_repo, "shot_9_2", spec)
    assert not rule_consumed_end(case)
    held = berry.model_copy(update={"end": ObjectState(held_by="S1")})
    others = [o for o in spec.objects or [] if o.name != "Strawberry"]
    stale = replace(case, spec=spec.model_copy(update={"objects": [held, *others]}))
    assert rule_consumed_end(stale)


@pytest.mark.parametrize(
    ("size", "dressing_in_frame"),
    [("MCU", False), ("CU", False), ("MS", True), ("WS", True)],
)
def test_set_dressing_in_frame_only_at_ms_or_wider(
    tmp_repo: Repo, default_cfg: Config, size: str, dressing_in_frame: bool
) -> None:
    seed_feed(tmp_repo, size=size)
    spec = _spec(tmp_repo, default_cfg, "shot_9_2")
    assert _obj(spec, "Strawberry").in_frame  # held and targeted: always expected
    assert _obj(spec, "Wooden Dining Table").in_frame is dressing_in_frame
    assert _obj(spec, "Blue Door").in_frame is dressing_in_frame


def _cam(size: str) -> CameraSpec:
    return CameraSpec(shot_size=size, angle="eye", movement="static", lens_mm=50)  # type: ignore[arg-type]


def test_tight_camera_only_for_one_in_place_action_on_one_subject() -> None:
    pick = InteractionStep(
        step_index=1, actor_id=PIP, target_id=BERRY, action="picks up the berry"
    )
    pet = InteractionStep(
        step_index=2, actor_id=PIP, target_id="char_milo", action="pets Milo"
    )
    walk = InteractionStep(
        step_index=3, actor_id=PIP, target_id=DOOR, action="walks to the door"
    )
    chars = [PIP, "char_milo"]
    assert not plan_framing(_cam("CU"), [pick], chars).widened
    for steps in ([pick, pet], [pet], [walk]):
        decision = plan_framing(_cam("CU"), steps, chars)
        assert decision.camera.shot_size == "MS" and "CU" in decision.intent
    assert not plan_framing(_cam("MLS"), [pick, pet], chars).widened


def test_lint_flags_and_s7_widens_a_disallowed_close_up(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_feed(tmp_repo, size="CU")
    assert "CAMERA_TOO_TIGHT" not in _codes(tmp_repo, default_cfg, "shot_9_1")
    issues = [
        i
        for i in lint_shot(tmp_repo, default_cfg, "shot_9_2")
        if i.code.endswith("TOO_TIGHT")
    ]
    assert issues and fix_cameras(tmp_repo, issues).fixes
    shot = tmp_repo.get_shot("shot_9_2")
    assert shot is not None and shot.camera.shot_size == "MS"
    assert shot.look is None or "framing intent CU" in shot.look.camera_motion_intent
    assert "CAMERA_TOO_TIGHT" not in _codes(tmp_repo, default_cfg, "shot_9_2")

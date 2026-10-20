"""Phase 1: clip↔event windows, lifecycles and per-clip props on a replay-derived graph."""

from __future__ import annotations

from kitchen_seed import BERRY, PIP, PUDDLE, TOWEL, seed_kitchen
from storygraph.budget import RefPlan
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.omni.spec import OmniClipSpec
from storygraph.repo import Repo
from storygraph.state import state_at
from storygraph.timeline.clip_context import story_lifecycles
from storygraph.views import shot_view


def _spec(repo: Repo, cfg: Config, shot_id: str) -> OmniClipSpec:
    pkg = compile_shot(shot_view(repo, shot_id), RefPlan(), cfg)
    return OmniClipSpec.model_validate_json(pkg.compiled_prompt)


def test_clip_after_consumption_never_lists_the_eaten_object(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    """004_02 regression: positional order 41 said 'Pip holds the strawberry' after Milo ate it."""
    seed_kitchen(tmp_repo)
    assert state_at(tmp_repo, PIP, 41).get("holding") == BERRY  # the old sampling point
    view = shot_view(tmp_repo, "shot_4_2")
    assert view.shot.covers_event_ids == [
        "evt_025",
        "evt_026",
        "evt_027",
        "evt_028",
        "evt_029",
    ]
    assert "holding" not in view.cast_states[PIP]
    assert BERRY not in view.shot.prop_ids and BERRY not in view.prop_states
    spec = _spec(tmp_repo, default_cfg, "shot_4_2")
    assert all(s.holding is None for s in spec.subjects or [])
    assert "Strawberry" not in spec.render()


def test_consuming_clip_shows_the_object_then_marks_it_consumed(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_kitchen(tmp_repo)
    view = shot_view(tmp_repo, "shot_4_1")
    assert view.shot.covers_event_ids[0] == "evt_020"
    # Pip picks the strawberry up and feeds it within this clip: neither edge shows it held.
    assert (
        "holding" not in view.cast_states[PIP]
        and "holding" not in view.cast_end_states[PIP]
    )
    berry = next(
        o
        for o in _spec(tmp_repo, default_cfg, "shot_4_1").objects or []
        if o.name == "Single Strawberry"
    )
    assert berry.moves and berry.end is not None and berry.end.where == "eaten by Milo"


def test_prop_rest_place_comes_from_its_own_facts_not_actor_support(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_kitchen(tmp_repo)
    scene = tmp_repo.get_scene("scn_4")
    assert scene is not None
    floor = [
        s.model_copy(update={"supported_by": "kitchen floorboards"})
        for s in scene.interaction_steps
    ]
    tmp_repo.put_scene(scene.model_copy(update={"interaction_steps": floor}))
    view = shot_view(tmp_repo, "shot_4_2")
    assert view.prop_states[TOWEL]["supported_by"] == "beside sink"
    towel = next(
        o
        for o in _spec(tmp_repo, default_cfg, "shot_4_2").objects or []
        if o.name == "Kitchen Towel"
    )
    assert towel.start.where == "beside sink" and "floorboards" not in (
        towel.start.where or ""
    )


def test_shot_story_order_and_scene_event_ids_follow_the_clip_events(
    tmp_repo: Repo,
) -> None:
    seed_kitchen(tmp_repo)
    shot2, scene = tmp_repo.get_shot("shot_4_2"), tmp_repo.get_scene("scn_4")
    assert shot2 is not None and scene is not None
    assert shot2.story_order == 45 and shot2.covers_event_ids[0] == "evt_025"
    assert scene.event_ids == [
        f"evt_0{n}" for n in range(20, 30)
    ]  # stale evt_017 dropped


def test_noop_restatements_open_no_new_state_fact(tmp_repo: Repo) -> None:
    seed_kitchen(tmp_repo)
    locs = [
        f for f in tmp_repo.list_state_facts(entity_id=PIP) if f.attribute == "location"
    ]
    assert [(f.valid_from_order, f.value) for f in locs] == [(44, "loc_cafe")]


def test_emergent_puddle_does_not_exist_before_its_evidence(tmp_repo: Repo) -> None:
    seed_kitchen(tmp_repo)
    life = story_lifecycles(tmp_repo)[PUDDLE]
    assert life.exists_from is not None and not life.alive_at(life.exists_from - 1)
    assert story_lifecycles(tmp_repo)[BERRY].exists_until == 43

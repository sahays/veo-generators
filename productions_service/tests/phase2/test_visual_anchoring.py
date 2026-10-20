"""Phase 2 visual anchoring: setting sheet reservation, approved-only chaining, state looks."""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.adapters.mock import MockImageGenerator, MockVLMProvider
from storygraph.adapters.omni.inputs import plan_image_slots
from storygraph.adapters.omni.package import RefLabel
from storygraph.agents.design_studio import design_single_entity
from storygraph.anchors.chaining import resolve_chain_frame
from storygraph.budget import select_references
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import (
    Appearance,
    Asset,
    CastInShot,
    Entity,
    EntityType,
    GenerationRun,
    InteractionStep,
    Role,
    Shot,
    Status,
)
from storygraph.views import ShotView, shot_view

_CHARS = ("char_a", "char_b", "char_c", "char_d", "char_e")
_PROPS = ("obj_p1", "obj_p2", "obj_p3")


def _add_sheet(repo: Repo, eid: str, label: str, kind: str) -> Asset:
    app = repo.add_appearance(
        Appearance(
            id=f"app_{eid}_{label}",
            created_by=Role.DESIGNER,
            status=Status.APPROVED,
            entity_id=eid,
            state_label=label,
            visual_description=f"{eid} {label} look",
        )
    )
    asset = repo.add_asset(
        Asset(
            id=f"ast_{eid}_{label}",
            created_by=Role.DESIGNER,
            status=Status.APPROVED,
            kind=kind,  # type: ignore[arg-type]
            uri=f"gs://b/{eid}_{label}.png",
            sha256=f"sha_{eid}_{label}",
            depicts_entity_ids=[eid],
            appearance_ids=[app.id],
            generation_prompt="sheet",
            model="mock",
        )
    )
    repo.update_appearance_status(app.id, Status.APPROVED, asset_ids=[asset.id])
    return asset


def _add_entity(repo: Repo, eid: str, etype: EntityType, kind: str) -> None:
    repo.put_entity(
        Entity(
            id=eid,
            created_by=Role.SCRIPT_SUPERVISOR,
            entity_type=etype,
            canonical_name=eid.upper(),
        )
    )
    _add_sheet(repo, eid, "default", kind)


def _crowded_view(repo: Repo) -> ShotView:
    """Shot with 6 on-screen characters (5 + Arjun) and 4 props: far more than 6 slots."""
    shot = seed_valid_graph(repo)
    for cid in _CHARS:
        _add_entity(repo, cid, EntityType.CHARACTER, "character_sheet")
    for pid in _PROPS:
        _add_entity(repo, pid, EntityType.OBJECT, "prop_sheet")
    cast = [CastInShot(entity_id=c, framing="CU", speaking=True) for c in _CHARS]
    repo.put_shot(
        shot.model_copy(
            update={
                "cast": [*shot.cast, *cast],
                "prop_ids": [*shot.prop_ids, *_PROPS],
                "camera": shot.camera.model_copy(update={"shot_size": "CU"}),
            }
        )
    )
    return shot_view(repo, "shot_1")


def _frame(repo: Repo, aid: str) -> Asset:
    return repo.add_asset(
        Asset(
            id=aid,
            created_by=Role.PIPELINE,
            status=Status.APPROVED,
            kind="first_frame",
            uri=f"gs://b/{aid}.png",
            sha256=f"sha_{aid}",
            generation_prompt="last frame",
            model="ffmpeg",
        )
    )


def _run(repo: Repo, shot_id: str, attempt: int, status: Status, frame: str) -> None:
    repo.add_generation_run(
        GenerationRun(
            id=f"run_{shot_id}_{attempt}",
            created_by=Role.PIPELINE,
            status=status,
            shot_id=shot_id,
            attempt=attempt,
            provider="mock",
            model="mock",
            compiled_prompt="{}",
            seed=attempt,
            package_hash=f"h{attempt}",
            extracted_last_frame_asset_id=_frame(repo, frame).id,
        )
    )


def _two_shot_scene(repo: Repo, continue_flag: bool, same_place: bool) -> Shot:
    first = seed_valid_graph(repo)
    if not same_place:
        _add_entity(repo, "loc_street", EntityType.LOCATION, "location_plate")
    return repo.put_shot(
        first.model_copy(
            update={
                "id": "shot_2",
                "index_in_scene": 2,
                "story_order": 16,
                "continue_from_last_frame": continue_flag,
                "location_id": "loc_cafe" if same_place else "loc_street",
                "location_appearance_id": "",
            }
        )
    )


def test_setting_sheet_reserved_even_when_characters_overflow(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    view = _crowded_view(tmp_repo)
    caps = default_cfg.video.model_copy(update={"max_reference_images": 6})
    plan = select_references(view, default_cfg, caps=caps, repo=tmp_repo)
    kinds = [a.kind for a in plan.selected_assets]
    assert kinds.count("location_plate") == 1
    assert "prop_sheet" not in kinds  # every character outranks every prop
    depicted = {e for a in plan.selected_assets for e in a.depicts_entity_ids}
    assert {"char_arjun", *_CHARS} <= depicted  # all six faces via composites


def test_slot_planner_keeps_location_when_truncating() -> None:
    chars = [
        RefLabel(uri=f"gs://b/{c}.png", asset_id=c, names=(c,), role="character")
        for c in _CHARS
    ]
    loc = RefLabel(
        uri="gs://b/loc.png", asset_id="loc", names=("Cafe",), role="location"
    )
    slots = plan_image_slots([*chars, loc], "gs://b/ff.png", 4)
    assert slots.first_frame_uri == "gs://b/ff.png"
    assert len(slots.refs) == 3 and loc in slots.refs
    assert [r.role for r in slots.refs][:2] == ["character", "character"]


def test_slot_cap_counts_first_frame(tmp_repo: Repo, default_cfg: Config) -> None:
    view = _crowded_view(tmp_repo).model_copy(
        update={"prev_shot_last_frame": _frame(tmp_repo, "ast_ff")}
    )
    caps = default_cfg.video.model_copy(update={"max_reference_images": 6})
    plan = select_references(view, default_cfg, caps=caps, repo=tmp_repo)
    assert plan.first_frame is not None
    assert len(plan.selected_assets) + 1 <= 6
    assert any(a.kind == "location_plate" for a in plan.selected_assets)
    assert not any(a.kind == "prop_sheet" for a in plan.selected_assets)
    assert len(plan.dropped_to_verbal) >= len(view.prop_entities) >= 1


def test_first_frame_never_taken_from_failed_latest_run(tmp_repo: Repo) -> None:
    shot_2 = _two_shot_scene(tmp_repo, continue_flag=True, same_place=True)
    _run(tmp_repo, "shot_1", 1, Status.APPROVED, "ast_lf_ok")
    _run(tmp_repo, "shot_1", 2, Status.FAILED, "ast_lf_bad")
    assert resolve_chain_frame(tmp_repo, shot_2) is None
    assert shot_view(tmp_repo, shot_2.id).prev_shot_last_frame is None


def test_first_frame_chained_from_approved_same_place_predecessor(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot_2 = _two_shot_scene(tmp_repo, continue_flag=False, same_place=True)
    _run(tmp_repo, "shot_1", 1, Status.FAILED, "ast_lf_bad")
    _run(tmp_repo, "shot_1", 2, Status.APPROVED, "ast_lf_ok")
    frame = resolve_chain_frame(tmp_repo, shot_2)
    assert frame is not None and frame.id.startswith("ast_lf_ok")
    view = shot_view(tmp_repo, shot_2.id)
    plan = select_references(view, default_cfg, repo=tmp_repo)
    assert plan.first_frame is not None and plan.first_frame.id == frame.id


def test_no_chaining_across_a_location_change_without_flag(tmp_repo: Repo) -> None:
    shot_2 = _two_shot_scene(tmp_repo, continue_flag=False, same_place=False)
    _run(tmp_repo, "shot_1", 1, Status.APPROVED, "ast_lf_ok")
    assert resolve_chain_frame(tmp_repo, shot_2) is None


def _prop_state_view(repo: Repo, opening: str) -> ShotView:
    view = shot_view(repo, "shot_1")
    states = {"obj_compass": {**view.prop_states["obj_compass"], "pre_state": opening}}
    return view.model_copy(update={"prop_states": states})


def test_reference_uses_appearance_matching_opening_state(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    wet = _add_sheet(tmp_repo, "obj_compass", "wet", "prop_sheet")
    soaked = _prop_state_view(tmp_repo, "the compass lies soaked on the counter")
    plan = select_references(soaked, default_cfg, repo=tmp_repo)
    prop_ids = {a.id for a in plan.selected_assets if a.kind == "prop_sheet"}
    assert prop_ids == {wet.id}
    dry = _prop_state_view(tmp_repo, "the compass is not wet yet")
    plan = select_references(dry, default_cfg, repo=tmp_repo)
    prop_ids = {a.id for a in plan.selected_assets if a.kind == "prop_sheet"}
    assert prop_ids == {"ast_obj_compass_default_v1"}


def test_design_studio_mints_state_appearance_from_graph(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    step = InteractionStep(
        step_index=2,
        actor_id="char_arjun",
        target_id="obj_compass",
        interaction_type="prop",
        action="Arjun drops the compass in the sink",
        post_state="the compass is dripping wet",
    )
    tmp_repo.put_scene(
        scene.model_copy(update={"interaction_steps": [*scene.interaction_steps, step]})
    )
    design_single_entity(
        tmp_repo, default_cfg, "obj_compass", MockImageGenerator(), MockVLMProvider()
    )
    wet = [
        a for a in tmp_repo.list_appearances("obj_compass") if a.state_label == "wet"
    ]
    assert len(wet) == 1 and wet[0].asset_ids
    assert "wet" in wet[0].condition_tags

"""Regression tests for the compiled Omni machine spec (JSON schema, order, refs, speech, budget)."""

from __future__ import annotations

import json
import re

import pytest
from omni_seed import _CLIP1, _MILO_DESC, _entity, _seed_shots
from storygraph.adapters.omni.inputs import build_omni_request
from storygraph.adapters.omni.package import build_ref_labels, to_render_package
from storygraph.budget import RefPlan, select_references
from storygraph.clips.species import ActorKind, entity_traits
from storygraph.clips.species_validation import (
    CODE_MUTE_SPEAKER,
    CODE_SPECIES_ACTION,
    validate_species_rules,
)
from storygraph.clips.text import has_timestamps
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.omni.spec import ObjectSpec, OmniClipSpec
from storygraph.omni.voice import build_speaker
from storygraph.repo import Repo
from storygraph.schema import Asset, DialogueLine, EntityType, Role
from storygraph.views import shot_view

_RAW_ID_RE = re.compile(r"\b(?:obj|char|loc|ast|shot|scn|evt|app|dlg)_\w+")
_SECONDS_RE = re.compile(r"\d+(?:\.\d+)?\s*s\)|\bt=\d")
_BANNED_RE = re.compile(r"\bNEVER\b|\bZERO\b|\bAVOID\b")
_BANNED_CI_RE = re.compile(r"duplicat|vanish|materializ", re.IGNORECASE)


@pytest.fixture()
def prompts(tmp_repo: Repo, default_cfg: Config) -> dict[str, str]:
    _seed_shots(tmp_repo)
    out: dict[str, str] = {}
    for sid in ("shot_1", "shot_2"):
        view = shot_view(tmp_repo, sid)
        plan = select_references(view, default_cfg, repo=tmp_repo)
        out[sid] = compile_shot(view, plan, default_cfg).compiled_prompt
    return out


def _spec(prompt: str) -> OmniClipSpec:
    return OmniClipSpec.model_validate(json.loads(prompt))


def _by_name(spec: OmniClipSpec, name: str) -> ObjectSpec:
    return next(o for o in spec.objects or [] if o.name == name)


def test_prompt_is_one_valid_compact_spec_without_ids_or_failure_words(
    prompts: dict[str, str],
) -> None:
    for sid, prompt in prompts.items():
        spec = _spec(prompt)
        assert prompt == spec.render(), sid  # canonical, compact, None-free
        assert ": " not in prompt.split('"summary"')[0] and "null" not in prompt
        assert not _RAW_ID_RE.search(prompt), (sid, _RAW_ID_RE.findall(prompt))
        assert "None" not in prompt and ".." not in prompt
        assert not has_timestamps(prompt) and not _SECONDS_RE.search(prompt)
        assert not _BANNED_RE.search(prompt) and not _BANNED_CI_RE.search(prompt)
        assert spec.clip.audio.music is False
    assert _spec(prompts["shot_1"]).summary == _CLIP1  # after the sequence


def test_sequence_follows_clip_step_order_with_symbolic_ids(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_shots(tmp_repo)
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    swapped = scene.clips[0].model_copy(update={"step_indices": [2, 1]})
    tmp_repo.put_scene(scene.model_copy(update={"clips": [swapped, scene.clips[1]]}))
    view = shot_view(tmp_repo, "shot_1")
    spec = _spec(compile_shot(view, RefPlan(), default_cfg).compiled_prompt)
    seq = spec.sequence or []
    assert [(s.n, s.actor, s.verb) for s in seq] == [
        (1, "S2", "sniffs the puddle"),
        (2, "S1", "unhooks the kitchen towel"),
    ]
    towel = _by_name(spec, "Kitchen Towel")
    assert seq[1].target == towel.id and seq[0].target == spec.setting.id


def test_object_states_are_shot_scoped(prompts: dict[str, str]) -> None:
    s1, s2 = _spec(prompts["shot_1"]), _spec(prompts["shot_2"])
    chair = _by_name(s1, "Wooden Chair")
    assert chair.moves is False and chair.end is None
    assert chair.start.where == "beside the dining table"
    towel = _by_name(s1, "Kitchen Towel")
    assert towel.moves is True and towel.start.where == "the towel hangs on wall peg"
    assert towel.end is not None and towel.end.where == "Pip holds the towel"
    assert "chair" not in prompts["shot_2"].lower()
    assert all("bowl" not in p.lower() for p in prompts.values())
    assert "linework" not in prompts["shot_1"] and "gouache" not in prompts["shot_1"]
    assert s2.continuity is not None
    assert s2.continuity.opening_state == "Pip holds the towel; the peg is empty"


def test_sounds_are_deduped_capped_and_action_relevant(prompts: dict[str, str]) -> None:
    sfx = _spec(prompts["shot_1"]).clip.audio.sfx or []
    assert len(sfx) <= 3 and len(set(sfx)) == len(sfx)
    assert "Fabric snap as the towel leaves the peg" in sfx
    assert sum("snap" in s.lower() for s in sfx) == 1  # near-duplicate snaps collapse


def test_speech_only_for_speakers_and_lipsync_follows_mouth(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_shots(tmp_repo)
    tmp_repo.put_dialogue(
        DialogueLine(
            id="dlg_milo",
            created_by=Role.SCREENWRITER,
            scene_id="scn_1",
            order_in_scene=2,
            speaker_id="char_milo",
            text="Woof words",
            language="hindi",
        )
    )
    shot = tmp_repo.get_shot("shot_1")
    assert shot is not None
    tmp_repo.put_shot(shot.model_copy(update={"dialogue_ids": ["dlg_pip", "dlg_milo"]}))
    view = shot_view(tmp_repo, "shot_1")
    spec = _spec(compile_shot(view, RefPlan(), default_cfg).compiled_prompt)
    subj = {s.id: s for s in spec.subjects or []}
    speech = spec.speech or []
    assert [(s.speaker, s.text, s.after) for s in speech] == [
        ("S1", "Stay back, Milo!", 1)  # anchored before the final step
    ]
    assert subj["S1"].has_mouth is False and speech[0].lipsync is False
    assert "robotic" in speech[0].voice
    assert subj["S2"].can_speak is False and subj["S2"].vocal


def test_ref_image_tokens_match_adapter_image_order(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_shots(tmp_repo)
    view = shot_view(tmp_repo, "shot_1")
    kinds = {"char_milo": "character_sheet", "obj_towel": "prop_sheet"}
    kinds |= {"char_pip": "character_sheet", "loc_cafe": "location_plate"}
    assets = [
        Asset(
            id=f"ast_{eid}",
            created_by=Role.DESIGNER,
            kind=kind,
            uri=f"gs://b/{eid}.png",
            sha256=eid,
            depicts_entity_ids=[eid],
            generation_prompt="g",
            model="m",
        )
        for eid, kind in kinds.items()
    ]
    caps = default_cfg.video.model_copy(update={"max_reference_images": 3})
    pkg = compile_shot(view, RefPlan(selected_assets=assets), default_cfg, caps=caps)
    spec = _spec(pkg.compiled_prompt)
    labels = build_ref_labels(view, assets)
    req = build_omni_request(
        to_render_package(pkg, labels, "p", "", ""), pkg.compiled_prompt, 3
    )
    captions = [b["text"] for b in req.blocks[1:] if b["type"] == "text"]
    sent = {re.search(r"<(IMAGE_REF_\d)>", c).group(1): c for c in captions}  # type: ignore[union-attr]
    bound = {s.name: s.ref_image for s in spec.subjects or []}
    bound |= {o.name: o.ref_image for o in spec.objects or []}
    bound[spec.setting.name] = spec.setting.ref_image
    assert bound["Pip"] == "IMAGE_REF_0" and "Pip identity" in sent["IMAGE_REF_0"]
    assert bound["Milo"] == "IMAGE_REF_1" and "Milo identity" in sent["IMAGE_REF_1"]
    assert bound["Cafe"] == "IMAGE_REF_2" and "Cafe identity" in sent["IMAGE_REF_2"]
    assert bound["Kitchen Towel"] is None  # 4th ref exceeds the 3-image cap
    assert "refs_are_identity_only" in spec.constraints


def test_robot_with_delicate_description_is_not_an_animal() -> None:
    pip = _entity("char_pip", EntityType.CHARACTER, "Pip")
    desc = "Rendered with delicate linework, Pip is a small teal robot. He sits beside Milo's dog bed."
    spk = build_speaker(pip, "Pip", desc, ["Milo"])
    assert spk.traits.kind == ActorKind.ROBOT and "animal" not in spk.profile
    girl = entity_traits(
        _entity("char_ana", EntityType.CHARACTER, "Ana"),
        "A delicate girl holding a puppy.",
        [],
    )
    assert girl.kind == ActorKind.PERSON and girl.can_speak


def test_species_validation_flags_wrong_vocalizer_only(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    bad = scene.clips[1].model_copy(
        update={
            "omni_prompt": "Pip kneels, barks a warning at Milo. Pip hears Milo bark."
        }
    )
    scene = scene.model_copy(update={"clips": [scene.clips[0], bad]})
    ents = tmp_repo.list_entities()
    traits = {
        e.id: entity_traits(e, "", [])
        for e in ents
        if e.entity_type == EntityType.CHARACTER
    }
    traits["char_milo"] = entity_traits(
        tmp_repo.get_entity("char_milo"), _MILO_DESC, ["Pip"]
    )
    names = {e.id: e.canonical_name for e in ents}
    milo_line = DialogueLine(
        id="dlg_m",
        created_by=Role.SCREENWRITER,
        scene_id="scn_1",
        order_in_scene=2,
        speaker_id="char_milo",
        text="Hello",
    )
    issues = validate_species_rules(scene, [milo_line], traits, names)
    species = [i for i in issues if i.code == CODE_SPECIES_ACTION]
    assert len(species) == 1 and "Pip" in species[0].message
    assert [i.code for i in issues if i.code == CODE_MUTE_SPEAKER] == [
        CODE_MUTE_SPEAKER
    ]


def test_step_species_rule_attributes_verb_to_its_own_subject(tmp_repo: Repo) -> None:
    """p-zyt0jprz regression: 'Pip glares … as Milo barks' must not flag Pip."""
    _seed_shots(tmp_repo)
    scene = tmp_repo.get_scene("scn_1")
    assert scene is not None
    ents = tmp_repo.list_entities()
    traits = {
        e.id: entity_traits(e, "", [])
        for e in ents
        if e.entity_type == EntityType.CHARACTER
    }
    traits["char_milo"] = entity_traits(
        tmp_repo.get_entity("char_milo"), _MILO_DESC, ["Pip"]
    )
    names = {e.id: e.canonical_name for e in ents}
    ok = "Pip glares at Milo, looks at the puddle, and stares ahead as Milo barks."
    bad = "Pip kneels and barks at Milo."
    steps = [
        scene.interaction_steps[0].model_copy(
            update={"step_index": i, "actor_id": "char_pip", "action": txt}
        )
        for i, txt in ((1, ok), (2, bad))
    ]
    scene = scene.model_copy(update={"interaction_steps": steps, "clips": []})
    issues = validate_species_rules(scene, [], traits, names)
    flagged = [i.message for i in issues if i.code == CODE_SPECIES_ACTION]
    assert len(flagged) == 1 and flagged[0].startswith("Step 2: Pip")


def test_retry_targets_kept_and_budget_trims_identity_not_sequence(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    _seed_shots(tmp_repo)
    view = shot_view(tmp_repo, "shot_1")
    goal = "After Pip takes the towel, the wall peg is empty"
    full = compile_shot(view, RefPlan(), default_cfg, retry_feedback=[goal])
    assert len(full.compiled_prompt) <= 2500
    budget = len(full.compiled_prompt) - 200
    caps = default_cfg.video.model_copy(update={"max_prompt_chars": budget})
    trimmed = compile_shot(
        view, RefPlan(), default_cfg, caps=caps, retry_feedback=[goal]
    )
    big, small = _spec(full.compiled_prompt), _spec(trimmed.compiled_prompt)
    assert small.must_achieve == [goal] and len(trimmed.compiled_prompt) <= budget
    assert small.sequence == big.sequence and small.speech == big.speech
    assert trimmed.package_hash != full.package_hash

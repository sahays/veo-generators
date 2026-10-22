"""Species rules: idioms and noun uses are not vocalizations; hybrid beings classify right."""

from __future__ import annotations

import pytest
from storygraph.clips.species import ActorKind, detect_traits
from storygraph.clips.species_validation import (
    CODE_SPECIES_ACTION,
    validate_species_rules,
)
from storygraph.schema import ClipScript, InteractionStep, Role, Scene

_PERSON = detect_traits(["A stern old sergeant, a man of few words."], {})
_DOG = detect_traits(["A scruffy terrier dog."], {})
_TRAITS = {"char_sarge": _PERSON, "char_rex": _DOG}
_NAMES = {"char_sarge": "Sarge", "char_rex": "Rex"}


def _flags(text: str) -> list[str]:
    scene = Scene(
        id="scn_1", created_by=Role.SCREENWRITER, index=1, heading="X", location_id="loc_x",
        time_of_day="day",
        interaction_steps=[InteractionStep(step_index=1, actor_id="char_sarge", interaction_type="environment", action=text)],
        clips=[ClipScript(clip_index=1, step_indices=[1], omni_prompt=text)],
    )  # fmt: skip
    issues = validate_species_rules(scene, [], _TRAITS, _NAMES)
    return [i.message for i in issues if i.code == CODE_SPECIES_ACTION]


@pytest.mark.parametrize(
    "text",
    [
        "Sarge barks an order at the recruits.",
        "Sarge barked out a curt command.",
        'Sarge barks: "Move!"',
        "Sarge purrs with amusement as the plan works.",
        "Sarge grabs the branch and his boot slips on the slick bark.",
        "Sarge peels the rough bark of the birch.",
        "Sarge watches as Rex barks at the door.",
    ],
)
def test_idioms_nouns_and_other_subjects_are_not_flagged(text: str) -> None:
    assert _flags(text) == []


def test_literal_person_bark_is_flagged_once_per_text_with_actionable_message() -> None:
    flags = _flags("Sarge drops to all fours and barks at the cat.")
    assert len(flags) == 2  # the step and the clip prompt
    assert all("Sarge (person)" in f and "rewrite" in f for f in flags)


def test_explicit_species_attribute_beats_person_words_for_mythic_beings() -> None:
    vanara = detect_traits(
        ["Angada Prince Angada youthful vanara prince", "Tawny fur and a muzzle."],
        {"species": "vanara", "age": "youthful late-teens vanara prince"},
    )
    assert (vanara.kind, vanara.can_speak, vanara.has_mouth) == (
        ActorKind.HYBRID,
        True,
        True,
    )


@pytest.mark.parametrize(
    ("tiers", "attrs", "kind", "speaks"),
    [
        (["A wise old bear."], {"species": "bear"}, ActorKind.ANIMAL, False),
        (["A talking rabbit with a waistcoat."], {}, ActorKind.HYBRID, True),
        (["A fox."], {"species": "mechanical fox"}, ActorKind.ROBOT, True),
        (["A loyal dog."], {"species": "robotic dog"}, ActorKind.ROBOT, True),
        (["A centaur archer."], {}, ActorKind.HYBRID, True),
        (["A golden retriever puppy with a red collar."], {}, ActorKind.ANIMAL, False),
    ],
)
def test_species_kind_comes_from_attributes_and_identity_text(
    tiers: list[str], attrs: dict[str, str], kind: ActorKind, speaks: bool
) -> None:
    traits = detect_traits(tiers, attrs)
    assert (traits.kind, traits.can_speak) == (kind, speaks)


def test_hybrid_beings_may_vocalize_like_their_animal_side() -> None:
    traits = {"char_v": detect_traits(["A vanara warrior."], {"species": "vanara"})}
    scene = Scene(
        id="scn_1", created_by=Role.SCREENWRITER, index=1, heading="X", location_id="loc_x",
        time_of_day="day", clips=[ClipScript(clip_index=1, step_indices=[], omni_prompt="Vali barks at the sky.")],
    )  # fmt: skip
    assert validate_species_rules(scene, [], traits, {"char_v": "Vali"}) == []

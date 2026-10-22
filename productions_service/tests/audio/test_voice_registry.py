"""Voice registry: deterministic, trait-aware, collision-free, never reassigned once fixed."""

from __future__ import annotations

import pytest
from storygraph.audio.voice.archetype import classify_archetype, own_context
from storygraph.audio.voice.registry import (
    assign_cast_voices,
    ensure_cast_voices,
    pick_voice_name,
    set_voice,
)
from storygraph.repo import Repo
from storygraph.schema import (
    AttributeVal,
    Entity,
    EntityType,
    Provenance,
    Role,
    VoiceProfile,
)

SOURCE = (
    "Characters: Pip, a small teal robot. Ava, a young mechanic. Mira, a young engineer. "
    "Ava enters the workshop with a box in her hand. She sets it down. "
    "Pip hands Ava the key. Mira checks her notes. She frowns. "
    "The key sits beside the red toolbox."
)


def _ent(eid: str, name: str, **attrs: str) -> Entity:
    return Entity(
        id=eid,
        created_by=Role.STORY_ARCHITECT,
        entity_type=EntityType.CHARACTER,
        canonical_name=name,
        attributes={
            k: AttributeVal(value=v, provenance=Provenance.FROM_TEXT)
            for k, v in attrs.items()
        },
    )


def _cast() -> list[Entity]:
    key = Entity(
        id="obj_key",
        created_by=Role.STORY_ARCHITECT,
        entity_type=EntityType.OBJECT,
        canonical_name="key",
    )
    return [
        _ent("char_pip", "Pip", type="small teal robot"),
        _ent("char_ava", "Ava", age="young adult"),
        _ent("char_mira", "Mira", age="young adult"),
        key,
    ]


def test_archetypes_from_traits_and_pronouns_props_do_not_hide_sentences() -> None:
    cast = _cast()
    # "Pip hands Ava the key." names a prop; prop names must not exclude Ava's sentences.
    assert "her hand" in own_context(SOURCE, ["Ava"], ["Pip", "Mira"])
    assert classify_archetype(cast[0], SOURCE, ["Ava", "Mira"]) == "robot"
    assert classify_archetype(cast[1], SOURCE, ["Pip", "Mira"]) == "adult_female"


def test_selection_is_deterministic_order_independent_and_collision_free() -> None:
    cast = _cast()
    speakers = cast[:3]
    first = assign_cast_voices(speakers, cast, SOURCE, "m")
    again = assign_cast_voices(list(reversed(speakers)), cast, SOURCE, "m")
    assert {k: v.voice_name for k, v in first.items()} == {
        k: v.voice_name for k, v in again.items()
    }
    # Ava and Mira share the adult_female pool but must not share a voice.
    assert first["char_ava"].voice_name != first["char_mira"].voice_name
    assert pick_voice_name("char_x", "robot", set()) == pick_voice_name(
        "char_x", "robot", set()
    )


def test_existing_voice_is_never_reassigned_and_blocks_reuse() -> None:
    cast = _cast()
    fixed = VoiceProfile(
        voice_name="Kore", archetype="adult_female", selected_by="human"
    )
    cast[2] = cast[2].model_copy(update={"voice": fixed})
    out = assign_cast_voices(cast[:3], cast, SOURCE, "m")
    assert out["char_mira"] == fixed
    assert out["char_ava"].voice_name != "Kore"


def test_ensure_persists_once_and_set_voice_validates(tmp_repo: Repo) -> None:
    tmp_repo.put_source_text(SOURCE)
    for e in _cast():
        tmp_repo.put_entity(e)
    voices = ensure_cast_voices(tmp_repo, ["char_ava", "char_pip"])
    version = tmp_repo.get_entity("char_ava").version  # type: ignore[union-attr]
    assert ensure_cast_voices(tmp_repo, ["char_ava"])["char_ava"] == voices["char_ava"]
    assert tmp_repo.get_entity("char_ava").version == version  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        set_voice(tmp_repo, "char_ava", "NotAVoice")
    edited = set_voice(tmp_repo, "char_ava", "Aoede")
    assert edited.voice is not None and edited.voice.selected_by == "human"
    assert ensure_cast_voices(tmp_repo, ["char_ava"])["char_ava"].voice_name == "Aoede"

"""Keyframe VLM check comparison: per-entity duplicates, missing props, pose/outfit, position."""

from __future__ import annotations

from storygraph.keyframes.plan.models import (
    CameraKey,
    CharacterKey,
    Keyframe,
    ObjectKey,
)
from storygraph.keyframes.render.prompts import drawn_props
from storygraph.keyframes.render.validation import (
    EntitySeen,
    KeyframeCheck,
    check_prompt,
    compare,
    parse_expected,
)


def _frame() -> Keyframe:
    return Keyframe(
        t=3,
        beat_index=0,
        phase=0.6,
        snapshot_index=1,
        characters=[
            CharacterKey(
                entity_id="char_pip",
                name="Pip",
                wardrobe="teal chassis",
                pose="midway: Pip kneels before the chest",
                position="left",
                x=0.22,
            ),
            CharacterKey(
                entity_id="char_ava",
                name="Ava",
                wardrobe="yellow jacket",
                pose="stays in place, attentive to Pip",
                position="right",
                x=0.78,
            ),
        ],
        objects=[
            ObjectKey(
                entity_id="obj_chest",
                name="Wooden Chest",
                placement="under the workbench",
            ),
            ObjectKey(
                entity_id="obj_cab", name="Blue Cabinet", placement="by the wall"
            ),
            ObjectKey(
                entity_id="obj_cloth",
                name="Green Cloth",
                placement="in drawer",
                visible=False,
            ),
        ],
        setting="Workshop",
        camera=CameraKey(
            shot_size="MS", angle="eye", movement="static", progress=0.3, framing="MS"
        ),
    )


def _drawn() -> list[str]:
    return [o.name for o in drawn_props(_frame(), set())]


def _seen(**over: EntitySeen) -> list[EntitySeen]:
    base = {
        "Pip": EntitySeen(name="Pip", present=True, count=1, x=0.25),
        "Ava": EntitySeen(name="Ava", present=True, count=1, x=0.75),
        "Wooden Chest": EntitySeen(name="wooden chest", present=True, count=1),
        "Blue Cabinet": EntitySeen(name="Blue Cabinet", present=True, count=1),
    }
    return list({**base, **over}.values())


def _issues(check: KeyframeCheck) -> list[str]:
    return compare(_frame(), check, _drawn())


def test_matching_frame_has_no_issues_and_hidden_objects_are_not_required() -> None:
    assert _drawn() == ["Wooden Chest", "Blue Cabinet"]  # hidden cloth not drawn
    assert _issues(KeyframeCheck(entities=_seen())) == []


def test_duplicate_chest_and_missing_cabinet_are_flagged_per_entity() -> None:
    seen = _seen(
        **{
            "Wooden Chest": EntitySeen(name="Wooden Chest", present=True, count=2),
            "Blue Cabinet": EntitySeen(name="Blue Cabinet", present=False),
        }
    )
    assert _issues(KeyframeCheck(entities=seen)) == [
        "Wooden Chest: appears 2 times",
        "Blue Cabinet: missing",
    ]


def test_pose_mismatch_names_only_that_character() -> None:
    seen = _seen(Pip=EntitySeen(name="Pip", present=True, count=1, pose_matches=False))
    issues = _issues(KeyframeCheck(entities=seen))
    assert len(issues) == 1 and issues[0].startswith("Pip: pose should be")
    assert "Ava" not in issues[0]


def test_outfit_mismatch_and_extra_characters() -> None:
    seen = _seen(
        Ava=EntitySeen(name="Ava", present=True, count=1, outfit_matches=False)
    )
    issues = _issues(KeyframeCheck(entities=seen, extra_characters=2))
    assert issues == [
        "Ava: outfit differs from reference",
        "remove 2 extra character(s)",
    ]


def test_position_tolerance_boundary() -> None:
    near = _seen(Pip=EntitySeen(name="Pip", present=True, count=1, x=0.45))
    far = _seen(Pip=EntitySeen(name="Pip", present=True, count=1, x=0.5))
    assert _issues(KeyframeCheck(entities=near)) == []  # |0.23| within 0.25
    assert _issues(KeyframeCheck(entities=far)) == ["Pip: at x=0.50, expected x=0.22"]


def test_missing_character_is_flagged() -> None:
    seen = [e for e in _seen() if e.name != "Ava"]
    assert _issues(KeyframeCheck(entities=seen)) == ["Ava: missing"]


def test_mock_answer_parsed_from_check_prompt_passes() -> None:
    """The offline VLM mock must agree with the prompt format, or every mock run fails."""
    for with_previous in (False, True):
        prompt = check_prompt(_frame(), _drawn(), with_previous=with_previous)
        check = parse_expected(prompt)
        assert sorted(e.name for e in check.entities) == [
            "Ava",
            "Blue Cabinet",
            "Pip",
            "Wooden Chest",
        ]
        assert _issues(check) == []

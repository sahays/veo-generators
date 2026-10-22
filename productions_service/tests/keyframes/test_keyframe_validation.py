"""Keyframe VLM check comparison: duplicates, vanishing props, outfit and role swaps."""

from __future__ import annotations

from storygraph.keyframes.plan.models import (
    CameraKey,
    CharacterKey,
    Keyframe,
    ObjectKey,
)
from storygraph.keyframes.render.validation import (
    CharacterSeen,
    KeyframeCheck,
    ObjectCount,
    PoseSeen,
    compare,
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
            ),
            CharacterKey(
                entity_id="char_ava",
                name="Ava",
                wardrobe="yellow jacket",
                pose="stays in place, attentive to Pip",
                position="right",
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


def _check(**kw: object) -> KeyframeCheck:
    base: dict[str, object] = {
        "objects": [
            ObjectCount(name="wooden chest", count=1),
            ObjectCount(name="Blue Cabinet", count=1),
        ],
        "characters": [
            CharacterSeen(name="Pip", present=True, outfit_matches=True),
            CharacterSeen(name="Ava", present=True, outfit_matches=True),
        ],
        "poses": [
            PoseSeen(name="Pip", matches_pose=True),
            PoseSeen(name="Ava", matches_pose=True),
        ],
    }
    return KeyframeCheck.model_validate({**base, **kw})


def test_matching_frame_has_no_issues_and_hidden_objects_are_not_required() -> None:
    assert compare(_frame(), _check()) == []


def test_duplicate_chest_and_vanished_cabinet_are_flagged() -> None:
    issues = compare(
        _frame(), _check(objects=[ObjectCount(name="Wooden Chest", count=2)])
    )
    assert any("Wooden Chest must appear exactly once (seen 2)" in i for i in issues)
    assert any(i.startswith("Blue Cabinet is missing") for i in issues)


def test_role_swap_and_outfit_change_are_flagged() -> None:
    issues = compare(
        _frame(),
        _check(
            characters=[
                CharacterSeen(name="Pip", present=True, outfit_matches=True),
                CharacterSeen(name="Ava", present=True, outfit_matches=False),
            ],
            poses=[
                PoseSeen(name="Pip", matches_pose=False),
                PoseSeen(name="Ava", matches_pose=False),
            ],
            extra_characters=1,
        ),
    )
    assert (
        "Pip (and nobody else) must be: midway: Pip kneels before the chest" in issues
    )
    assert "Ava must wear exactly: yellow jacket" in issues
    assert "remove 1 extra character(s)" in issues

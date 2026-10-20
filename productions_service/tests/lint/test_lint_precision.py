"""Linter precision regressions from the live p-zyt0jprz S7 replay (8 blocking messages).

Live text is used verbatim so the detector is held to what the screenwriter really writes.
"""

from __future__ import annotations

import pytest

from storygraph.clips.limits import camera_follows_locomotion, count_spoken_words
from storygraph.schema import InteractionStep
from storygraph.timeline.locomotion import find_locomotion, is_key_action

# True positives: a main verb moves the actor through space.
_LOCOMOTION = (
    ("Pip approaches the wooden table and stretches his mechanical arms upward, failing to reach the bowl.", "approach"),
    ("walks to the wooden chair and grasps the top rail of its backrest with both metallic hands", "walk"),
    ("Pip walks over to the low countertop and places the ceramic bowl securely onto its surface.", "walk"),
    ("Pip releases the chair, claps his palms clean, and strides confidently toward the blue door.", "stride"),
    ("stands up, stretches, and trots directly into Pip's forward chair trajectory, blocking the path", "trot"),
    ("Pip pushes open the pastel blue door and steps across the threshold into the sunlit kitchen.", "step"),
    ("Pip carries the bowl to the counter.", "carry"),
    ("Pip crosses the kitchen to the sink.", "cross"),
    ("Milo ran out of the kitchen.", "run"),
)  # fmt: skip
# False positives the old regex produced: in-place motion, subordinate clauses, participles.
_IN_PLACE = (
    "Pip lifts the ceramic bowl from the table with both hands and steps down backward from the wooden chair onto the kitchen floor.",
    "Pip crashes down onto his chassis with a loud clatter as Milo trots over.",
    "Pip kneels down and tenders the strawberry to Milo, who takes and swallows it.",
    "Milo spins rapidly chasing his tail and collides his flank hard against the rear legs of the wooden chair.",
    "shoves the chair flush against the dining table, releases the backrest, and climbs onto the chair seat",
    "Pip moves the chair to the wall.",
    "Pip crosses his arms and waits.",
)  # fmt: skip


@pytest.mark.parametrize(("text", "lemma"), _LOCOMOTION)
def test_main_verb_locomotion_is_detected(text: str, lemma: str) -> None:
    hit = find_locomotion(text)
    assert hit is not None and hit.lemma == lemma


@pytest.mark.parametrize("text", _IN_PLACE)
def test_in_place_or_subordinate_motion_is_not_locomotion(text: str) -> None:
    assert find_locomotion(text) is None


def test_crossing_is_lateral_but_approach_is_not() -> None:
    cross = find_locomotion("Pip crosses the kitchen to the sink.")
    approach = find_locomotion("Pip approaches the wooden table.")
    assert cross is not None and cross.lateral
    assert approach is not None and not approach.lateral


@pytest.mark.parametrize(
    ("size", "move", "ok"),
    [
        ("MS", "dolly_in", True),  # live scn_002/004/006 messages: now compatible
        ("MCU", "dolly_in", False),
        ("MCU", "tilt_up", False),  # live scn_001 clip 2: true positive
        ("MCU", "static", False),
        ("WS", "static", True),
        ("MLS", "static", False),
        ("CU", "track", True),
        ("ECU", "pan_l", True),
        ("MCU", "handheld", True),
        ("EWS", "tilt_down", False),
    ],
)
def test_locomotion_camera_policy(size: str, move: str, ok: bool) -> None:
    assert camera_follows_locomotion(size, move) is ok


def test_key_action_needs_handling_or_travel() -> None:
    def step(action: str, target: str | None = "obj_chair") -> InteractionStep:
        return InteractionStep(
            step_index=1, actor_id="char_pip", target_id=target, action=action
        )

    assert is_key_action(step("grabs the wooden chair"))
    assert is_key_action(step("trots over to the puddle", target=None))
    assert not is_key_action(step("stares at the wooden chair"))
    assert not is_key_action(step("crashes down as Milo trots over", target=None))


def test_devanagari_words_are_not_split_on_vowel_signs() -> None:
    """Live scn_001 clip 2 reported '25 spoken words' for 13 Hindi words (regex `\\w` split)."""
    lines = ("वाह, मेज़ पर ताज़े स्ट्रॉबेरी!", "हाथ नहीं पहुँच रहा... वो कुर्सी काम आएगी।")
    assert [count_spoken_words(t) for t in lines] == [5, 8]
    assert count_spoken_words("Well -- that's it ... done!") == 4

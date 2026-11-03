"""Keyword rules for previz blocking (pure): body pose from the planner's pose text.

The planner's pose text is `"<stage> <action>"` for the acting character (stage is
`starting:` / `midway:` / `finishing:` while the beat plays, `about to:` / `has just
finished:` around it) and a neutral phrase for everyone else. Only an in-progress action
selects an action pose. A moving character walks so feet never slide, except while it
pushes / shoves / heaves / closes something it is touching: then it keeps the `push`
pose (pushing a cabinet across the floor is a moving push, not a walk).
"""

from __future__ import annotations

import re
from typing import Final

from ...schemas.previz_scene import Pose

_IN_PROGRESS: Final[tuple[str, ...]] = ("starting:", "midway:", "finishing:")
_POSE_RULES: Final[tuple[tuple[Pose, tuple[str, ...]], ...]] = (
    ("push", ("push", "shove", "heave", "close", "slam", "nudge", "shut", "drag")),
    ("crouch", ("kneel", "crouch", "bend", "squat", "stoop")),
    ("sit", ("sit", "seated")),
    ("reach", ("reach", "lift", "take", "grab", "press", "open", "pull", "pick")),
    ("point", ("point",)),
)
_WORD = re.compile(r"[a-z]+")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _inflects(word: str, key: str) -> bool:
    """`word` is `key` or a verb inflection of it (s/es/ed/ing, dropped e, doubled
    consonant): `closes`, `shoving`, `sitting` match; `closer`, `pointer` do not."""
    stem = key[:-1] if key.endswith("e") else key
    if word == key or not word.startswith(stem):
        return False
    rest = word[len(stem) :]
    return rest in {"s", "es", "ed", "d", "ing", "e"} or rest in {
        key[-1] + "ing",
        key[-1] + "ed",
    }


def _has(words: set[str], keys: tuple[str, ...]) -> bool:
    return any(w == k or _inflects(w, k) for w in words for k in keys)


def action_pose(text: str) -> Pose:
    """The in-progress action's pose (`stand` when nothing is in progress)."""
    lowered = text.lower().strip()
    if not lowered.startswith(_IN_PROGRESS):
        return "stand"
    words = _words(lowered)
    return next((pose for pose, keys in _POSE_RULES if _has(words, keys)), "stand")


def body_pose(text: str, moving: bool, in_contact: bool = False) -> Pose:
    """Pose for the planner's pose text; `moving` = the character moves this second,
    `in_contact` = it is within arm's reach of its beat target (a moving push only then;
    walking up to the cabinet it will push is still a walk)."""
    pose = action_pose(text)
    if moving:
        return "push" if pose == "push" and in_contact else "walk"
    return pose

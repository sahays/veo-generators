"""Character body from text (pure): archetype, height and walking speed.

Rules run on the character's name + the subject clause of its description first (so "a
woman carrying a toy robot" stays human), then on the full description + wardrobe. The
first rule (ordered: quadrupeds, robots, creatures, children, adults) whose keyword is a
whole word wins; robots are `small_robot` unless the text says humanoid / android / tall,
and "small / tiny / little" shrink a robot or creature. An explicit height in the text
("1.2 m tall", "90 cm tall", "4 feet tall") overrides the rule height. Quadruped heights
are at the shoulder. Speeds bound every blocking path (m/s).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ...schemas.previz_scene import Archetype
from ..layout.kinds import subject_clause

_WORD = re.compile(r"[a-z]+")
_EXPLICIT = re.compile(r"(\d+(?:\.\d+)?)\s*(m|cm|metres?|meters?|feet|foot|ft)\s+tall")
_UNIT: Final[dict[str, float]] = {
    "m": 1.0,
    "cm": 0.01,
    "feet": 0.3048,
    "foot": 0.3048,
    "ft": 0.3048,
}
_RULES: Final[tuple[tuple[Archetype, float, tuple[str, ...]], ...]] = (
    ("quadruped", 1.5, ("horse", "pony", "donkey", "cow", "deer")),
    ("quadruped", 0.3, ("puppy", "cat", "kitten", "fox", "rabbit")),
    ("quadruped", 0.5, ("dog", "hound", "wolf", "quadruped", "pup")),
    ("human", 1.8, ("humanoid", "android", "cyborg")),
    ("small_robot", 1.0, ("robot", "droid", "bot", "automaton", "drone")),
    ("creature", 0.7, ("creature", "critter", "monster", "alien", "goblin", "gnome", "imp", "sprite", "fairy", "blob")),
    ("human", 0.9, ("toddler", "baby", "infant")),
    ("human", 1.25, ("child", "kid", "boy", "girl", "children")),
    ("human", 1.6, ("teen", "teenager", "adolescent")),
    ("human", 1.72, ("man", "woman", "person", "adult", "mechanic", "inventor", "human")),
)  # fmt: skip
_SMALL: Final[tuple[str, ...]] = (
    "small",
    "tiny",
    "little",
    "compact",
    "mini",
    "miniature",
)
_TALL: Final[tuple[str, ...]] = ("tall", "towering", "giant", "huge", "large", "big")
_SPEED: Final[dict[str, float]] = {
    "human": 1.8, "small_robot": 1.2, "quadruped": 2.5, "creature": 1.5,
}  # fmt: skip
DEFAULT: Final[tuple[Archetype, float]] = ("human", 1.72)


@dataclass(frozen=True)
class Body:
    archetype: Archetype
    height_m: float
    max_speed: float  # m/s bound on every path step


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _has(words: set[str], keys: tuple[str, ...]) -> bool:
    return any(k in words or f"{k}s" in words for k in keys)


def _rule(text: str) -> tuple[Archetype, float] | None:
    words = _words(text)
    for archetype, height, keys in _RULES:
        if _has(words, keys):
            return archetype, height
    return None


def _scaled(archetype: Archetype, height: float, words: set[str]) -> float:
    if archetype in ("small_robot", "creature") and _has(words, _SMALL):
        return round(height * 0.9, 3)
    if _has(words, _TALL):
        return round(height * (1.08 if archetype == "human" else 1.4), 3)
    return height


def explicit_height(text: str) -> float | None:
    m = _EXPLICIT.search(text.lower())
    if m is None:
        return None
    unit = m.group(2)
    scale = _UNIT.get(unit, 1.0 if unit.startswith("met") else 0.3048)
    return round(min(max(float(m.group(1)) * scale, 0.2), 3.0), 3)


def character_body(name: str, description: str, wardrobe: str = "") -> Body:
    """Archetype + height (m) + speed bound for one cast member."""
    subject = f"{name} {subject_clause(description)}"
    full = f"{name} {description} {wardrobe}"
    archetype, height = _rule(subject) or _rule(full) or DEFAULT
    height = _scaled(archetype, height, _words(subject))
    if (explicit := explicit_height(full)) is not None:
        height = explicit
    speed = _SPEED[archetype] * (0.8 if height < 1.3 and archetype == "human" else 1.0)
    return Body(archetype, height, round(speed, 2))

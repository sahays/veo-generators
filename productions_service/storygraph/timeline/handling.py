"""Who physically handles which prop in a clip (manipulation vs. merely looking at it).

`InteractionStep.target_id` is overloaded ("stares at the puddle" targets the puddle), so a
step only *moves* its target when its text has a manipulation verb, and an object can only
be *held* when it is not a fixture, liquid or location-like thing.
"""

from __future__ import annotations

import re
from typing import Final

from ..schema import InteractionStep

MANIPULATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:grab|grasp|grip|pick|pluck|lift|carr|hold|held|push|pull|drag|tug|move|unhook|"
    r"hook|remov|wring|squeez|stack|pour|"
    r"place|set[s]?\b|put|drop|throw|toss|open|close|shut|fold|wipe|scrub|mop|knock|"
    r"tip|spill|pour|hands? (?:over|it)|give|gave|offer|take|took|eat|ate|bite|munch|"
    r"slide|tuck|hang|shove|kick|catch|fetch|clutch|swipe)\w*",
    re.IGNORECASE,
)
LOCOMOTION_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:walk|stride|strode|cross|trot|march|run|ran|scurr|dart|stroll|approach|"
    r"step(?:s|ped)? (?:over|toward|forward|across|down|back)|hurr|dash|wander|"
    r"head(?:s|ed)? (?:to|toward)|crawl|climb|pace|zoom|rush)\w*",
    re.IGNORECASE,
)
_UNHOLDABLE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:puddle|spill|liquid|water|juice|milk|door|doorway|floor|floorboards|wall|"
    r"counter|countertop|sink|window|table|shelf|rack|stove|fridge|cabinet|kitchen|"
    r"room|ground|stairs?|bed|sofa|couch)\b",
    re.IGNORECASE,
)


def head_noun(name: str) -> str:
    """Head noun of an English noun phrase: 'Bowl of Strawberries' -> 'bowl'."""
    phrase = re.split(r"\s+of\s+", name.strip().lower(), maxsplit=1)[0]
    words = re.findall(r"[a-z]+", phrase)
    if not words:
        return ""
    word = words[-1]
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def is_holdable(name: str) -> bool:
    """False for fixtures, liquids and location-like objects (by head noun)."""
    return not _UNHOLDABLE_RE.search(head_noun(name))


def step_text(step: InteractionStep) -> str:
    return " ".join(p for p in (step.action, step.detail) if p.strip())


def manipulates(step: InteractionStep) -> bool:
    return bool(step.target_id) and bool(MANIPULATION_RE.search(step_text(step)))


def moved_props(steps: list[InteractionStep]) -> dict[str, str]:
    """`prop_id -> actor_id` for targets the clip's steps physically manipulate."""
    out: dict[str, str] = {}
    for st in steps:
        if st.target_id and manipulates(st):
            out.setdefault(st.target_id, st.actor_id)
    return out


def has_locomotion(steps: list[InteractionStep]) -> bool:
    return any(LOCOMOTION_RE.search(step_text(s)) for s in steps)

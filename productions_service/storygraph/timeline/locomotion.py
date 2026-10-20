"""Locomotion detection from a step's MAIN verb(s) and a locomotion lexicon.

A step is locomotion only when a main-clause verb moves its actor through space ("walks to",
"strides toward", "crosses the room", "carries the bowl to the counter"). Subordinate clauses
("… as Milo trots over"), in-place motion (falls, crashes, sits, kneels, lifts, climbs onto)
and participles ("spins chasing his tail") are not locomotion.

Lookup is O(1) per token: every inflected surface form is precomputed into one dict.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

from ..schema import InteractionStep
from .handling import manipulates


class _Kind(Enum):
    FREE = "free"  # always locomotion as a main verb (walk, run, approach …)
    DIRECTED = "directed"  # needs a direction particle right after (step toward …)
    CARRY = "carry"  # needs a destination anywhere in the clause (carries X to Y)
    CROSS = "cross"  # locomotion unless crossing a body part (crosses his arms)


_FREE: Final[tuple[str, ...]] = (
    "walk", "run", "stride", "trot", "dash", "march", "approach", "enter", "exit",
    "chase", "stroll", "jog", "sprint", "hurry", "scurry", "scamper", "wander", "rush",
    "amble", "saunter", "waddle", "tiptoe", "retreat", "pace", "crawl",
)  # fmt: skip
_DIRECTED: Final[tuple[str, ...]] = (
    "step", "move", "head", "go", "come", "leave", "return",
)  # fmt: skip
_IRREGULAR: Final[dict[str, str]] = {
    "ran": "run", "strode": "stride", "went": "go", "came": "come", "left": "leave",
}  # fmt: skip
_DOUBLED: Final[frozenset[str]] = frozenset({"run", "trot", "step", "jog"})
_DIRECTIONS: Final[frozenset[str]] = frozenset(
    {"to", "toward", "towards", "into", "across", "through", "past", "away", "out",
     "forward", "along", "inside", "outside", "off"}
)  # fmt: skip
_BODY_PARTS: Final[frozenset[str]] = frozenset(
    {"arm", "arms", "leg", "legs", "finger", "fingers", "ankles", "eyes", "hands"}
)
_FILLERS: Final[frozenset[str]] = frozenset(
    {"over", "back", "up", "down", "right", "straight", "forth"}
)
_HEAD_WINDOW: Final[int] = 3  # a main verb sits within the first tokens of its clause
_BODY_WINDOW: Final[int] = 3  # "crosses his arms" → body part within 3 tokens
_SUBORDINATE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:,\s*|\s+)(?:as|while|when|whereupon|until|before|after|because|who|which|whose|"
    r"sending|causing|making|letting)\b",
    re.IGNORECASE,
)
_COORDINATE_RE: Final[re.Pattern[str]] = re.compile(
    r",\s*(?:and\s+|then\s+)?|;\s*|\s+and\s+(?:then\s+)?|\s+then\s+", re.IGNORECASE
)
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z']+")


def _forms(lemma: str) -> set[str]:
    """Regular inflections of a verb lemma (3rd person, past, gerund)."""
    if lemma.endswith("e"):
        out = {lemma + "s", lemma + "d", lemma[:-1] + "ing"}
    elif lemma.endswith("y") and lemma[-2] not in "aeiou":
        out = {lemma[:-1] + "ies", lemma[:-1] + "ied", lemma + "ing"}
    elif lemma.endswith(("s", "sh", "ch", "x", "o")):
        out = {lemma + "es", lemma + "ed", lemma + "ing"}
    else:
        out = {lemma + "s", lemma + "ed", lemma + "ing"}
    if lemma in _DOUBLED:
        out |= {lemma + lemma[-1] + "ing", lemma + lemma[-1] + "ed"}
    return out | {lemma}


def _build_lexicon() -> dict[str, tuple[str, _Kind]]:
    lex: dict[str, tuple[str, _Kind]] = {}
    groups: tuple[tuple[Iterable[str], _Kind], ...] = (
        (_FREE, _Kind.FREE),
        (_DIRECTED, _Kind.DIRECTED),
        (("carry",), _Kind.CARRY),
        (("cross",), _Kind.CROSS),
    )
    for lemmas, kind in groups:
        for lemma in lemmas:
            lex.update({form: (lemma, kind) for form in _forms(lemma)})
    for form, lemma in _IRREGULAR.items():
        lex[form] = (lemma, lex[lemma][1])
    return lex


_LEXICON: Final[dict[str, tuple[str, _Kind]]] = _build_lexicon()


@dataclass(frozen=True)
class LocomotionHit:
    """The main-clause locomotion found in a text."""

    lemma: str
    clause: str

    @property
    def lateral(self) -> bool:
        """A crossing move (suits a pan rather than a track)."""
        return self.lemma == "cross" or " across " in f" {self.clause.lower()} "


def main_clause(text: str) -> str:
    """`text` up to its first subordinate clause ("… as Milo trots over" is dropped)."""
    hit = _SUBORDINATE_RE.search(text)
    return text[: hit.start()] if hit else text


def _directed(after: list[str]) -> bool:
    """Direction right after the verb, allowing one filler: 'steps confidently toward',
    'comes over to' — but not 'moves the chair to' (that moves an object)."""
    head = (
        after[1:]
        if after and (after[0] in _FILLERS or after[0].endswith("ly"))
        else after
    )
    return bool(head) and head[0] in _DIRECTIONS


def _qualifies(kind: _Kind, after: list[str]) -> bool:
    if kind is _Kind.FREE:
        return True
    if kind is _Kind.DIRECTED:
        return _directed(after)
    if kind is _Kind.CARRY:
        return any(t in _DIRECTIONS for t in after)
    return not any(t in _BODY_PARTS for t in after[:_BODY_WINDOW])


def _clause_hit(clause: str) -> LocomotionHit | None:
    tokens = _TOKEN_RE.findall(clause.lower())
    for pos, tok in enumerate(tokens[:_HEAD_WINDOW]):
        entry = _LEXICON.get(tok)
        if entry and _qualifies(entry[1], tokens[pos + 1 :]):
            return LocomotionHit(entry[0], clause.strip())
    return None


def find_locomotion(text: str) -> LocomotionHit | None:
    """First main-verb locomotion in `text` (each coordinated clause checked), or None."""
    for clause in _COORDINATE_RE.split(main_clause(text)):
        hit = _clause_hit(clause)
        if hit is not None:
            return hit
    return None


def step_locomotion(step: InteractionStep) -> LocomotionHit | None:
    """Locomotion in a step's action (then its detail), judged clause by clause."""
    for part in (step.action or step.description, step.detail):
        hit = find_locomotion(part) if part.strip() else None
        if hit is not None:
            return hit
    return None


def is_key_action(step: InteractionStep) -> bool:
    """A key action travels (locomotion) or physically handles an object."""
    return manipulates(step) or step_locomotion(step) is not None

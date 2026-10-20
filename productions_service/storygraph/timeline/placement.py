"""Plain-word object placement: tell a location from a condition, phrase each, and cut text
on phrase boundaries.

Graph facts mix kinds in one attribute (`sub_location='closed'`, `'wiped clean'`,
`'near blue door'`); a value is a *location* when it carries a preposition or names a
surface, and a *condition* when every word is a state adjective/participle.
"""

from __future__ import annotations

import re
from typing import Final

PREPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        "on", "in", "at", "under", "beside", "against", "inside", "near", "by", "atop",
        "above", "below", "behind", "next", "upon", "across", "along", "into", "onto",
        "over", "underneath", "between", "around", "outside", "within", "off", "from",
        "toward", "towards", "through",
    }
)  # fmt: skip
_CONDITION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "open", "ajar", "shut", "upright", "clean", "dirty", "wet", "dry", "empty", "full",
        "broken", "fallen", "intact", "lit", "unlit", "sideways", "upside", "down", "askew",
        "crooked", "level", "flat", "half", "slightly", "fully", "partly", "wide", "tilted",
        "frozen", "torn", "bent", "whole", "damp", "soaked", "messy", "neat", "away",
    }
)  # fmt: skip
_FUNCTION_TAIL: Final[frozenset[str]] = PREPOSITIONS | frozenset(
    {"the", "a", "an", "and", "or", "but", "of", "to", "with", "while", "as", "his",
     "her", "its", "their", "very", "is", "are", "was"}
)  # fmt: skip
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z']+")
_PHRASE_BREAK_RE: Final[re.Pattern[str]] = re.compile(r"[,;:]\s+|(?<=[.!?])\s+")
_MIN_PARTICIPLE: Final[int] = 5


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _is_state_word(word: str) -> bool:
    participle = len(word) >= _MIN_PARTICIPLE and word.endswith("ed")
    return word in _CONDITION_WORDS or participle


def is_condition(value: str) -> bool:
    """'closed', 'wiped clean', 'tipped' -> True; 'by wall', 'kitchen floor' -> False."""
    words = _words(value)
    if not words or any(w in PREPOSITIONS for w in words):
        return False
    return all(_is_state_word(w) for w in words)


def surface_phrase(value: str) -> str:
    """A location phrase: prepositional/gerund phrases unchanged, bare surfaces get 'on the'."""
    text = value.strip()
    if not text or is_condition(text):
        return ""
    first = text.split(" ", 1)[0].lower()
    if first in PREPOSITIONS or first.endswith("ing"):
        return text
    return f"on the {text}"


def ends_dangling(text: str) -> bool:
    """True when `text` stops on a function word ('... on the') — a truncation artefact."""
    words = _words(text.strip().rstrip(".!?"))
    return bool(words) and words[-1] in _FUNCTION_TAIL


def condition_as_place(text: str) -> bool:
    """'on the closed' — a preposition + article wrapped around a bare condition."""
    words = _words(text)
    return (
        len(words) >= 3
        and words[0] in PREPOSITIONS
        and words[1] in {"the", "a", "an"}
        and is_condition(" ".join(words[2:]))
    )


def _drop_dangling(text: str) -> str:
    out = text.rstrip(" ,;:")
    while ends_dangling(out) and " " in out:
        out = out.rsplit(" ", 1)[0].rstrip(" ,;:")
    return out


def cut_phrase(text: str, limit: int) -> str:
    """`text` within `limit` chars, cut at the last phrase break (else word) that fits and
    never ending on a dangling function word."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    breaks = [m.start() for m in _PHRASE_BREAK_RE.finditer(head)]
    if breaks and breaks[-1] > limit // 2:
        cut = head[: breaks[-1]]
    else:
        cut = head.rsplit(" ", 1)[0]
    return _drop_dangling(cut)

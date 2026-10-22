"""Is an animal-vocal verb ("bark", "growl", "purr"…) really an animal vocalization?

Two general, story-agnostic exemptions, decided on the words around the match:

* **Noun use** — "the slick bark", "rough bark of the branch", "a low purr". Bare forms
  ("bark") are verbs only right after a subject/auxiliary (actor name, pronoun, modal,
  "to"); inflected forms ("barks", "barked") are nouns after a determiner or before "of".
* **Speech idiom** — the verb describes *how someone talks*: it takes a speech object
  ("barks an order", "growls a warning"), a manner phrase ("roars with laughter") or
  introduces a quote / colon ("barks: 'Move!'"). Idioms are speech, not vocalization.
"""

from __future__ import annotations

import re
from typing import Final

_DETERMINERS: Final[frozenset[str]] = frozenset(
    {
        "the", "a", "an", "its", "his", "her", "their", "my", "your", "our", "this",
        "that", "these", "those", "of", "some", "no", "any", "each", "tree", "birch",
        "oak", "pine", "cedar", "rough", "slick", "smooth", "damp", "wet", "dry",
        "mossy", "loose", "peeling", "low", "soft", "deep", "loud", "single",
    }
)  # fmt: skip
_VERB_CONTEXT: Final[frozenset[str]] = frozenset(
    {
        "to", "will", "would", "can", "could", "may", "might", "must", "should",
        "shall", "do", "does", "did", "not", "never", "he", "she", "they", "it", "i",
        "we", "you", "who", "suddenly", "loudly", "then", "also",
    }
)  # fmt: skip
_SPEECH_OBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:out\s+|back\s+)?(?:(?:a|an|the|his|her|their|its|another|one|sharp|quick|"
    r"curt|gruff|stern|low|short|final|last)\s+)*"
    r"(?:orders?|commands?|instructions?|warnings?|repl(?:y|ies)|responses?|answers?|"
    r"questions?|greetings?|threats?|names?|words?|insults?|directions?|reminders?)\b",
    re.IGNORECASE,
)
_MANNER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:out\s+)?(?:with|in)\s+(?:\w+\s+)?(?:laughter|laughs?|delight|glee|joy|"
    r"rage|anger|fury|frustration|pain|triumph|approval|disgust|contempt|amusement|"
    r"impatience|annoyance)\b",
    re.IGNORECASE,
)
_QUOTE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:out|back)?\s*(?:,|:|—|-)?\s*[\"'“‘«]", re.IGNORECASE
)
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[\w'-]+")
_INFLECTED_RE: Final[re.Pattern[str]] = re.compile(r"(?:s|ed|ing|ies|ied)$")


def _prev_word(text: str, start: int) -> str:
    words = _WORD_RE.findall(text[max(0, start - 40) : start])
    return words[-1].lower() if words else ""


def _next_word(text: str, end: int) -> str:
    m = _WORD_RE.search(text, end)
    return m.group(0).lower() if m else ""


def is_noun_use(text: str, start: int, end: int, subject_names: frozenset[str]) -> bool:
    """True when the match at [start, end) is a noun ("the bark", "bark of the tree")."""
    word = text[start:end].lower()
    prev = _prev_word(text, start)
    if prev in _DETERMINERS or _next_word(text, end) == "of":
        return True
    if _INFLECTED_RE.search(word):
        return False
    return prev not in _VERB_CONTEXT and prev not in subject_names


def is_speech_idiom(text: str, end: int) -> bool:
    """True when the verb ending at `end` describes speech manner, not an animal sound."""
    tail = text[end : end + 60]
    return bool(
        _SPEECH_OBJECT_RE.match(tail) or _MANNER_RE.match(tail) or _QUOTE_RE.match(tail)
    )


def is_vocalization(
    text: str, start: int, end: int, subject_names: frozenset[str]
) -> bool:
    """A literal animal vocalization: neither a noun use nor a speech idiom."""
    return not is_noun_use(text, start, end, subject_names) and not is_speech_idiom(
        text, end
    )

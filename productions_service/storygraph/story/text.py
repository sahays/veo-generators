"""Text normalization for story-beat comparison: tokens, stop-words, and light stemming."""

from __future__ import annotations

import re
from typing import Final

# Split on whitespace and punctuation only, so Devanagari combining marks stay in-word.
_SPLIT_RE: Final[re.Pattern[str]] = re.compile(
    r"[\s.,;:!?\"'`()\[\]{}<>/\\|*_~…—–\-‘’“”।]+"
)
_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "by",
        "for", "with", "from", "into", "onto", "over", "up", "down", "out", "off",
        "is", "are", "was", "were", "be", "been", "it", "its", "his", "her",
        "their", "them", "they", "he", "she", "him", "this", "that", "then",
        "as", "while", "again", "very", "just", "so", "says", "say", "said",
    }
)  # fmt: skip
_SUFFIXES: Final[tuple[str, ...]] = ("ing", "ies", "ed", "es", "s")
_MIN_STEM_LEN: Final[int] = 3


def stem(token: str) -> str:
    """Strip one common English inflection suffix (ASCII words only)."""
    if not token.isascii():
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM_LEN:
            return token[: -len(suffix)]
    return token


def content_tokens(text: str) -> frozenset[str]:
    """Return the set of stemmed, lower-cased content tokens in `text`."""
    raw = _SPLIT_RE.split(text.lower())
    return frozenset(stem(t) for t in raw if t and t not in _STOPWORDS)

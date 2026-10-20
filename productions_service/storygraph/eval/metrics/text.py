"""Language-aware text normalization and edit-distance similarity (Latin and Devanagari).

Normalization: NFKC, casefold, drop punctuation (incl. Devanagari danda/double danda), keep
combining marks (matras/virama) so Hindi words compare correctly. Edit distance is the classic
two-row Levenshtein DP: O(n*m) time, O(min(n, m)) memory.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

_DEVANAGARI = (0x0900, 0x097F)
_DEVA_LANGS = frozenset({"hi", "mr", "ne", "sa", "kok", "mai", "bho"})


def normalize(text: str) -> str:
    """Comparable form: NFKC + casefold, punctuation/symbols removed, whitespace collapsed."""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    kept = [
        " " if unicodedata.category(ch)[0] in ("P", "S", "Z", "C") else ch
        for ch in folded
    ]
    return " ".join("".join(kept).split())


def levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    """Edit distance between two token/char sequences."""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        cur = [i]
        for j, y in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def char_similarity(ref: str, hyp: str) -> float:
    """1 - CER on normalized, space-free strings (1.0 identical, 0.0 unrelated)."""
    r, h = normalize(ref).replace(" ", ""), normalize(hyp).replace(" ", "")
    if not r and not h:
        return 1.0
    return max(0.0, 1.0 - levenshtein(r, h) / max(len(r), len(h)))


def word_error_rate(ref: str, hyp: str) -> float:
    """Token-level WER of `hyp` against `ref` (can exceed 1.0 for long insertions)."""
    r, h = normalize(ref).split(), normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    return levenshtein(r, h) / len(r)


def script_of(text: str) -> str:
    """Dominant writing system of the letters in `text`: 'Deva', 'Latn', 'other' or ''."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return ""
    deva = sum(_DEVANAGARI[0] <= ord(ch) <= _DEVANAGARI[1] for ch in letters)
    latin = sum(ch.isascii() for ch in letters)
    best = max((deva, "Deva"), (latin, "Latn"), (len(letters) - deva - latin, "other"))
    return best[1]


def expected_script(lang: str) -> str:
    """Writing system a scripted line in `lang` (BCP-47) should be transcribed in."""
    base = (lang or "").split("-")[0].lower()
    if not base:
        return ""
    return "Deva" if base in _DEVA_LANGS else "Latn"


def same_language(lang: str, observed_lang: str, text: str) -> bool:
    """Language check: explicit codes when both known, else the transcript's script."""
    want = (lang or "").split("-")[0].lower()
    got = (observed_lang or "").split("-")[0].lower()
    if want and got:
        return want == got
    expected = expected_script(lang)
    return not expected or script_of(text) in ("", expected)

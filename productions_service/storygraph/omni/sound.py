"""SFX selection: union of the shot's sound lists, deduped, ranked by action relevance, capped."""

from __future__ import annotations

import re
from typing import Final

from ..schema import InteractionStep, Shot

MAX_SOUNDS: Final[int] = 3
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]{4,}")
_NEAR_DUP_OVERLAP: Final[float] = 0.6


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_WORD_RE.findall(text.lower()))


def _overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient: 'towel hook snap' vs 'fabric snap as the towel leaves' -> 0.67."""
    smaller = min(len(a), len(b))
    return len(a & b) / smaller if smaller else 1.0


def _candidates(shot: Shot, steps: list[InteractionStep]) -> list[tuple[int, str]]:
    """(source_rank, sound) in priority order; exact duplicates removed in O(n)."""
    sources: list[tuple[int, list[str]]] = [
        (0, [s.sound_trigger for s in steps]),
        (1, shot.action_focus_sfx),
        (2, shot.foley_sfx),
        (3, shot.sfx),
        (4, shot.environmental_sfx),
    ]
    seen: dict[str, tuple[int, str]] = {}
    for rank, items in sources:
        for raw in items:
            text = raw.strip().rstrip(".")
            key = " ".join(text.lower().split())
            if key and key not in seen:
                seen[key] = (rank, text)
    return list(seen.values())


def select_sounds(
    shot: Shot, steps: list[InteractionStep], action: str, cap: int = MAX_SOUNDS
) -> list[str]:
    """Pick the `cap` most action-relevant, mutually distinct sounds for this clip."""
    action_words = _tokens(action)
    scored = sorted(
        enumerate(_candidates(shot, steps)),
        key=lambda it: (-len(_tokens(it[1][1]) & action_words), it[1][0], it[0]),
    )
    picked: list[tuple[str, frozenset[str]]] = []
    for _, (_, text) in scored:
        toks = _tokens(text)
        if all(_overlap(toks, other) < _NEAR_DUP_OVERLAP for _, other in picked):
            picked.append((text, toks))
        if len(picked) >= cap:
            break
    return [t for t, _ in picked]

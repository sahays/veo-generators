"""Duplicate-beat detection over story beats (MinHash/LSH candidates + exact Jaccard check)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .beats import Beat, BeatKind
from .minhash import candidate_pairs, jaccard, signature

# Minimum Jaccard similarity of content tokens for two beats to count as the same beat.
_THRESHOLDS: Final[dict[BeatKind, float]] = {
    BeatKind.EVENT: 0.6,
    BeatKind.SCENE: 0.6,
    BeatKind.CLIP: 0.55,
    BeatKind.LINE: 0.75,
}
_MIN_TOKENS: Final[int] = (
    3  # shorter beats ("Yes!", "Milo sits") are too generic to judge
)
_CROSS_SCENE_ONLY: Final[frozenset[BeatKind]] = frozenset(
    {BeatKind.EVENT, BeatKind.SCENE, BeatKind.CLIP}
)


@dataclass(frozen=True)
class DuplicateBeat:
    """`repeat` re-does `original` (earlier in story order) with `similarity` Jaccard."""

    original: Beat
    repeat: Beat
    similarity: float


def _order(a: Beat, b: Beat) -> tuple[Beat, Beat]:
    return (
        (a, b) if (a.scene_index, a.node_id) <= (b.scene_index, b.node_id) else (b, a)
    )


def _is_duplicate(a: Beat, b: Beat, sim: float) -> bool:
    if sim < _THRESHOLDS[a.kind] or a.node_id == b.node_id:
        return False
    return a.kind not in _CROSS_SCENE_ONLY or a.scene_id != b.scene_id


def _duplicates_of_kind(beats: list[Beat]) -> list[DuplicateBeat]:
    sigs = [signature(b.tokens) for b in beats]
    found: list[DuplicateBeat] = []
    for i, j in candidate_pairs(sigs):
        a, b = beats[i], beats[j]
        sim = jaccard(a.tokens, b.tokens)
        if _is_duplicate(a, b, sim):
            original, repeat = _order(a, b)
            found.append(DuplicateBeat(original, repeat, round(sim, 3)))
    return found


def find_duplicate_beats(beats: Iterable[Beat]) -> list[DuplicateBeat]:
    """Return repeated beats per kind, sorted by (repeat scene index, repeat id)."""
    by_kind: dict[BeatKind, list[Beat]] = {}
    for beat in beats:
        if len(beat.tokens) >= _MIN_TOKENS and not beat.callback:
            by_kind.setdefault(beat.kind, []).append(beat)
    found = [d for group in by_kind.values() for d in _duplicates_of_kind(group)]
    found.sort(
        key=lambda d: (d.repeat.scene_index, d.repeat.node_id, d.original.node_id)
    )
    return found

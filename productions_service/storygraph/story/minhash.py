"""MinHash signatures + LSH banding: near-duplicate candidate pairs without O(n^2) comparison.

Each token set gets a `NUM_PERM`-wide MinHash signature (O(tokens * NUM_PERM)); signatures
are split into `BANDS` bands of `ROWS` rows and bucketed by band value. Only sets sharing a
bucket become candidate pairs, which callers verify with exact Jaccard. With 16x2 banding a
pair at Jaccard 0.5 is a candidate with p≈0.99 while unrelated sets (J≈0.05) rarely collide.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from itertools import combinations
from typing import Final

ROWS: Final[int] = 2
BANDS: Final[int] = 16
NUM_PERM: Final[int] = ROWS * BANDS
_PRIME: Final[int] = (1 << 61) - 1
_RNG: Final[random.Random] = random.Random(1729)  # fixed seed: deterministic signatures
_COEFFS: Final[tuple[tuple[int, int], ...]] = tuple(
    (_RNG.randrange(1, _PRIME), _RNG.randrange(0, _PRIME)) for _ in range(NUM_PERM)
)

Signature = tuple[int, ...]


def _token_hash(token: str) -> int:
    """Stable 64-bit token hash (Python's `hash` is salted per process)."""
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest())


def signature(tokens: frozenset[str]) -> Signature:
    """MinHash signature of a non-empty token set under `NUM_PERM` universal hashes."""
    hashes = [_token_hash(t) for t in tokens]
    return tuple(min((a * h + b) % _PRIME for h in hashes) for a, b in _COEFFS)


def candidate_pairs(signatures: Sequence[Signature]) -> set[tuple[int, int]]:
    """Index pairs `(i, j)`, `i < j`, sharing at least one LSH band bucket."""
    buckets: dict[tuple[int, Signature], list[int]] = {}
    for idx, sig in enumerate(signatures):
        for band in range(BANDS):
            key = (band, sig[band * ROWS : (band + 1) * ROWS])
            buckets.setdefault(key, []).append(idx)
    pairs: set[tuple[int, int]] = set()
    for members in buckets.values():
        pairs.update(combinations(members, 2))
    return pairs


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Exact Jaccard similarity of two token sets (0.0 when both are empty)."""
    union = len(a | b)
    return len(a & b) / union if union else 0.0

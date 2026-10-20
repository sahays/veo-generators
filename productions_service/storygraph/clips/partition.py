"""Contiguous, balanced step partitioning under per-clip caps (steps and key actions).

`min_groups_from` is an O(n · max_steps) suffix DP; `partition_steps` then walks left to
right picking the most balanced feasible chunk size, so the result uses exactly `n_groups`
groups whenever `n_groups >= min_groups_from(...)[0]`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .limits import CLIP_LIMITS, ClipLimits

_INF = 10**9


def _chunk_ok(keys: Sequence[bool], start: int, end: int, limits: ClipLimits) -> bool:
    size = end - start
    return (
        0 < size <= limits.max_clip_steps
        and sum(keys[start:end]) <= limits.max_key_actions
    )


def min_groups_from(
    keys: Sequence[bool], limits: ClipLimits = CLIP_LIMITS
) -> list[int]:
    """`out[i]` = fewest contiguous clips covering steps `i..` under the caps (`out[n] = 0`)."""
    n = len(keys)
    out = [_INF] * (n + 1)
    out[n] = 0
    for i in range(n - 1, -1, -1):
        for end in range(i + 1, min(n, i + limits.max_clip_steps) + 1):
            if _chunk_ok(keys, i, end, limits) and out[end] + 1 < out[i]:
                out[i] = out[end] + 1
    return out


def _sizes_by_preference(target: int, cap: int) -> list[int]:
    """Chunk sizes to try: `target` first, then outward (smaller before larger)."""
    order = [target]
    for delta in range(1, cap + 1):
        order += [target - delta, target + delta]
    return [s for s in order if 1 <= s <= cap]


def partition_steps(
    keys: Sequence[bool], n_groups: int, limits: ClipLimits = CLIP_LIMITS
) -> list[range]:
    """Split `len(keys)` steps into `n_groups` contiguous ranges obeying the caps.

    Falls back to the minimal feasible group count when `n_groups` is too small, and to
    fewer groups than requested only when there are fewer steps than groups.
    """
    n = len(keys)
    if n == 0:
        return []
    need = min_groups_from(keys, limits)
    groups = min(max(n_groups, need[0]), n)
    out: list[range] = []
    pos = 0
    for g in range(groups):
        left = groups - g
        target = math.ceil((n - pos) / left)
        for size in _sizes_by_preference(target, limits.max_clip_steps):
            end = pos + size
            if end > n:
                continue
            fits_rest = n - end >= left - 1 and need[end] <= left - 1
            if _chunk_ok(keys, pos, end, limits) and fits_rest:
                break
        else:
            end = (
                n if left == 1 else pos + 1
            )  # infeasible caps: degrade, never lose steps
        out.append(range(pos, end))
        pos = end
    return out

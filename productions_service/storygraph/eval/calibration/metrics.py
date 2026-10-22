"""Agreement statistics: binary confusion metrics and tie-aware Spearman rank correlation."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .contracts import BinaryMetrics


def binary(pred: Sequence[bool], gold: Sequence[bool]) -> BinaryMetrics:
    """Confusion counts with "pass" as the positive class."""
    m = BinaryMetrics()
    for p, g in zip(pred, gold, strict=True):
        if p and g:
            m.tp += 1
        elif p:
            m.fp += 1
        elif g:
            m.fn += 1
        else:
            m.tn += 1
    return m


def _ranks(values: Sequence[float]) -> list[float]:
    """1-based average ranks (ties share the mean of their positions) in O(n log n)."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Spearman rho (Pearson on average ranks); None when undefined (n<3 or constant)."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return round(cov / math.sqrt(vx * vy), 3)

"""Choose keyframe times from candidates: merge, bound gaps, split large motion, cap (pure).

1. `merge`: one sweep over time-sorted candidates; a candidate closer than `min_spacing_s`
   to the last kept one competes with it and the higher priority survives (endpoints always
   win; an event absorbed by the clip end lends it its label). O(n log n) for the sort.
2. `fill_gaps`: a gap longer than `max_gap_s` gets the best dropped candidate inside it (that
   keeps the spacing; binary search over the time-sorted drops), else the interpolated
   midpoint — recursively, so every gap ends up within the bound.
3. `split_motion`: a gap in which some character moves more than `motion_threshold_x` frame
   widths gets its midpoint (recursively, while both halves keep the spacing).
4. `cap`: over budget, keep t0 and tN plus `max_frames - 2` middles, filled tier by tier in
   (priority, kind) order (sort, O(n log n)); the tier that does not fit is thinned by
   farthest-point spreading (O(k * n), k <= budget), so equal events cover the whole clip
   instead of bunching at its start.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Sequence
from itertools import groupby
from typing import Final

from .models import FILLER, MOTION, STATE, Candidate, SamplingCfg

EPS: Final[float] = 1e-6
Displacement = Callable[[float, float], tuple[float, str]]  # (a, b) -> (dx, who)


def _wins(new: Candidate, old: Candidate) -> bool:
    return (new.priority, -new.rank) > (old.priority, -old.rank)


def _absorb(winner: Candidate, loser: Candidate) -> Candidate:
    """The clip end shows the closing state, so a state change it absorbs names it."""
    if winner.kind == "clip_end" and loser.priority == STATE:
        return winner.relabel(f"{loser.label} (clip end)")
    return winner


def merge(
    ordered: Sequence[Candidate], spacing: float
) -> tuple[list[Candidate], list[Candidate]]:
    """(kept, dropped) after the spacing sweep; `ordered` must be sorted by time."""
    kept: list[Candidate] = []
    dropped: list[Candidate] = []
    for cand in ordered:
        last = kept[-1] if kept else None
        both_ends = last is not None and last.is_endpoint and cand.is_endpoint
        if last is None or both_ends or cand.t - last.t >= spacing - EPS:
            kept.append(cand)
        elif _wins(cand, last):
            dropped.append(last)
            kept[-1] = _absorb(cand, last)
        else:
            dropped.append(cand)
            kept[-1] = _absorb(last, cand)
    return kept, dropped


def _best_inside(
    a: Candidate,
    b: Candidate,
    drops: Sequence[Candidate],
    times: Sequence[float],
    spacing: float,
) -> Candidate:
    lo = bisect_left(times, a.t + spacing - EPS)
    hi = bisect_right(times, b.t - spacing + EPS)
    mid = (a.t + b.t) / 2
    pool = drops[lo:hi]
    if not pool:
        return Candidate(round(mid, 3), FILLER, "interpolated", "in-between state")
    return max(pool, key=lambda c: (c.priority, -c.rank, -abs(c.t - mid)))


def _bridge(
    a: Candidate,
    b: Candidate,
    split: Callable[[Candidate, Candidate], Candidate | None],
) -> list[Candidate]:
    """Candidates inserted between `a` and `b` by recursive `split` (None = done)."""
    pick = split(a, b)
    if pick is None:
        return []
    return [*_bridge(a, pick, split), pick, *_bridge(pick, b, split)]


def _between(
    kept: Sequence[Candidate], split: Callable[[Candidate, Candidate], Candidate | None]
) -> list[Candidate]:
    out = list(kept[:1])
    for nxt in kept[1:]:
        out += [*_bridge(out[-1], nxt, split), nxt]
    return out


def fill_gaps(
    kept: Sequence[Candidate], dropped: Sequence[Candidate], cfg: SamplingCfg
) -> list[Candidate]:
    drops = sorted(dropped, key=lambda c: c.t)
    times = [c.t for c in drops]

    def split(a: Candidate, b: Candidate) -> Candidate | None:
        if cfg.max_gap_s is None or b.t - a.t <= cfg.max_gap_s + EPS:
            return None
        return _best_inside(a, b, drops, times, cfg.min_spacing_s)

    return _between(kept, split)


def split_motion(
    kept: Sequence[Candidate],
    cfg: SamplingCfg,
    moved: Displacement,
    names: dict[str, str],
) -> list[Candidate]:
    def split(a: Candidate, b: Candidate) -> Candidate | None:
        if b.t - a.t < 2 * cfg.min_spacing_s - EPS:
            return None
        dx, who = moved(a.t, b.t)
        if dx <= cfg.motion_threshold_x:
            return None
        label = f"{names.get(who, who)} midway across the frame"
        return Candidate(round((a.t + b.t) / 2, 3), MOTION, "motion", label)

    return _between(kept, split)


def _tier(c: Candidate) -> tuple[int, int]:
    return (-c.priority, c.rank)  # ascending sort = most important first


def _spread(
    tier: Sequence[Candidate], room: int, anchors: list[float]
) -> list[Candidate]:
    """`room` picks from `tier`, each the farthest from every time chosen so far."""
    pool, taken = list(tier), list(anchors)
    picks: list[Candidate] = []
    for _ in range(room):
        best = max(pool, key=lambda c: (min(abs(c.t - a) for a in taken), -c.t))
        pool.remove(best)
        picks.append(best)
        taken.append(best.t)
    return picks


def cap(kept: Sequence[Candidate], max_frames: int) -> list[Candidate]:
    if len(kept) <= max_frames:
        return list(kept)
    first, last = kept[0], kept[-1]
    chosen: list[Candidate] = []
    anchors = [first.t, last.t]
    for _, group in groupby(sorted(kept[1:-1], key=_tier), key=_tier):
        room = max_frames - 2 - len(chosen)
        tier = list(group)
        picks = tier if len(tier) <= room else _spread(tier, room, anchors)
        chosen += picks
        anchors += [c.t for c in picks]
        if len(chosen) >= max_frames - 2:
            break
    return [first, *sorted(chosen, key=lambda c: c.t), last]


def select(
    candidates: Sequence[Candidate],
    cfg: SamplingCfg,
    moved: Displacement | None = None,
    names: dict[str, str] | None = None,
) -> list[Candidate]:
    """Selected keyframe moments in time order (first = t0, last = tN)."""
    ordered = sorted(candidates, key=lambda c: (c.t, -c.priority, c.rank))
    kept, dropped = merge(ordered, cfg.min_spacing_s)
    kept = fill_gaps(kept, dropped, cfg)
    if moved is not None:
        kept = split_motion(kept, cfg, moved, names or {})
    return cap(kept, cfg.max_frames)

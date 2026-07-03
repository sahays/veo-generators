"""Rung ladder math + global rung assignment (Viterbi DP).

The "rung" is the crop-vs-letterbox decision: an inner aspect ratio from the
canvas's ladder (tightest full-bleed crop → loosest full-width letterbox).
Pure logic, no project imports — `reframe_plan` composes this with the content
decisions and re-exports the public names.
"""

import math
from typing import List, Optional, Tuple

# Inner-AR rungs, tightest crop → loosest (most letterbox). Chosen by coverage.
# 9:16 is the historical *adaptive* ladder: each scene picks a rung, letterboxing
# wide content. 3:4 is a *fixed* full-bleed crop — a single-rung ladder so every
# scene crops to fill the 3:4 frame (subject-following pan), never letterboxes.
RUNGS: List[Tuple[int, int]] = [(9, 16), (4, 5), (1, 1), (16, 9)]
RUNGS_BY_CANVAS: dict = {
    "9:16": RUNGS,
    "3:4": [(3, 4)],
}

RUNG_TOLERANCE = 0.05  # accept a rung that covers within this of the requirement


def rung_coverage(rung: Tuple[int, int], src_w: int, src_h: int) -> float:
    """Fraction of source width a rung's crop keeps (clamped to 1.0)."""
    aw, ah = rung
    return min(1.0, (src_h * aw / ah) / src_w)


def pick_rung(
    required: float,
    src_w: int,
    src_h: int,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> Tuple[int, int]:
    """Lowest rung whose coverage ≥ required (the segment's IDEAL rung).

    A small RUNG_TOLERANCE lets a tighter rung win when it *almost* covers the
    requirement — trading a sliver of edge crop for much less letterboxing (e.g.
    a two-shot needing 0.60 takes 1:1 at 0.5625 rather than full 16:9).

    `rungs` is the canvas's ladder (defaults to the 9:16 RUNGS). Temporal
    consistency (flip-flop damping, mid-shot stability) is NOT handled here —
    `assign_rungs` optimizes the whole sequence globally.
    """
    rungs = rungs or RUNGS
    return next(
        (
            r
            for r in rungs
            if rung_coverage(r, src_w, src_h) + RUNG_TOLERANCE >= required
        ),
        rungs[-1],
    )


# --- Global rung assignment (Viterbi DP) -------------------------------------
# Costs are in "bar-fraction × seconds" units. The greedy predecessor
# (pick_rung + one-step hysteresis) looked one segment back and produced
# locally-fine, globally-wrong plans: a single wide shot chained one-rung-loose
# through a whole vlog (ashley-trip), and verdicts popped bars mid-shot. The DP
# sees the whole sequence: it holds a looser rung ONLY when that genuinely
# prevents a second switch (true A-B-A flip-flop), re-tightens immediately when
# it doesn't, and prefers widening a whole shot over changing bars mid-shot.
DP_SWITCH_AT_CUT = 0.35  # per rung-step at a real scene cut (damps flip-flop)
DP_SWITCH_MID_SHOT = 3.0  # per rung-step mid-shot (bars pop with no cut to hide)
# Breakeven intuition: holding one rung loose costs ~0.30 bar-fraction × dur;
# at 0.35/step a hold beats a down-and-back-up switch pair (0.70) for cells
# under ~2.3s — i.e. flip-flops are damped, sustained waste is not tolerated.


def _bar_fraction(rung: Tuple[int, int], rungs: List[Tuple[int, int]]) -> float:
    """Fraction of the output canvas covered by letterbox bars at this rung.

    The canvas aspect equals the tightest (full-bleed) rung, so the foreground
    height ratio is (ah/aw) / (a0h/a0w) — no renderer import needed.
    """
    a0w, a0h = rungs[0]
    aw, ah = rung
    return max(0.0, 1.0 - (ah / aw) / (a0h / a0w))


def assign_rungs(
    cells: List[dict],
    src_w: int,
    src_h: int,
    rungs: Optional[List[Tuple[int, int]]] = None,
) -> List[Optional[Tuple[int, int]]]:
    """Globally-optimal rung per cell (None for split cells) via Viterbi DP.

    `cells`: [{"C": required coverage, "dur": seconds, "starts_at_cut": bool,
    "split": bool}] in time order. Per-cell allowed states are the rungs that
    cover `C` (with RUNG_TOLERANCE, falling back to the loosest — same
    guarantee as pick_rung: content is never cropped out). Emission cost =
    bar_fraction × dur (wasted screen); transition cost = rung-step distance ×
    (DP_SWITCH_AT_CUT at real cuts, DP_SWITCH_MID_SHOT mid-shot). Split cells
    break the chain (a split↔single change is already a layout cut).
    """
    rungs = rungs or RUNGS
    bars = [_bar_fraction(r, rungs) for r in rungs]
    out: List[Optional[Tuple[int, int]]] = [None] * len(cells)

    def _allowed(c):
        ok = [
            i
            for i, r in enumerate(rungs)
            if rung_coverage(r, src_w, src_h) + RUNG_TOLERANCE >= c["C"]
        ]
        return ok or [len(rungs) - 1]

    # Solve each maximal run of non-split cells independently.
    i = 0
    while i < len(cells):
        if cells[i].get("split"):
            i += 1
            continue
        j = i
        while j < len(cells) and not cells[j].get("split"):
            j += 1
        run = list(range(i, j))
        # Viterbi over the run.
        prev_cost = {}
        prev_ptr: List[dict] = []
        for k, ci in enumerate(run):
            cell = cells[ci]
            emis = {s: bars[s] * max(0.0, cell["dur"]) for s in _allowed(cell)}
            if k == 0:
                prev_cost = dict(emis)
                prev_ptr.append({s: None for s in emis})
                continue
            step = (
                DP_SWITCH_AT_CUT
                if cell.get("starts_at_cut", True)
                else DP_SWITCH_MID_SHOT
            )
            cost, ptr = {}, {}
            for s, e in emis.items():
                best_p, best_c = None, math.inf
                for p, pc in prev_cost.items():
                    c = pc + step * abs(s - p)
                    if c < best_c:
                        best_p, best_c = p, c
                cost[s], ptr[s] = best_c + e, best_p
            prev_cost = cost
            prev_ptr.append(ptr)
        # Backtrack.
        s = min(prev_cost, key=prev_cost.get)
        for k in range(len(run) - 1, -1, -1):
            out[run[k]] = rungs[s]
            s = prev_ptr[k][s] if prev_ptr[k][s] is not None else s
        i = j
    return out

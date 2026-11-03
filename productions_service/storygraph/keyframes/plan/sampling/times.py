"""Keyframe times of one clip for the configured sampling mode (pure)."""

from __future__ import annotations

from ..models import PlanInput
from ..state import names_of
from ..timing import second_count
from .extract import extract_candidates
from .models import FILLER, Candidate, SamplingCfg
from .select import Displacement, select


def clock(inp: PlanInput, cfg: SamplingCfg) -> tuple[float, float]:
    """(last keyframe time, motion grid step): 1 fps ends on round(duration) like before."""
    if cfg.mode == "fps":
        return float(second_count(inp.duration_s) - 1), 1.0
    return round(inp.duration_s, 3), cfg.grid_step_s


def sample_times(
    inp: PlanInput, cfg: SamplingCfg, moved: Displacement | None = None
) -> list[Candidate]:
    """Selected moments in time order; `fps` = every second, unlabelled (legacy plans)."""
    if cfg.mode == "fps":
        last = second_count(inp.duration_s) - 1
        return [Candidate(float(t), FILLER, None, "") for t in range(last + 1)]
    return select(extract_candidates(inp), cfg, moved, names_of(inp))

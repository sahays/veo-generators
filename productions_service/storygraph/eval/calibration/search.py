"""Gate-parameter search: coordinate descent over capped, monotone grids + leave-one-shot-out CV.

Two objectives (see `objective_key`), both on the kids-draft-acceptable target:
- `floor`: reach pass precision >= `min_precision`, then maximise recall (then strict F1).
- `fbeta`: maximise precision-weighted F-beta (beta=0.5), then strict F1, then accuracy.
On golden v1 the hard floor overfits (held-out precision collapses), so `fbeta` is shipped;
see docs/eval/eval_calibration_v1.md. A move is accepted only when it strictly improves the
key, so ties keep the earlier (closer to current) config. Camera adherence is never offered
as a hard gate (and `GateConfig.for_dimension` forbids it).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from ...config import DimensionName, GateConfig
from .contracts import BinaryMetrics, GoldenLabel
from .metrics import binary
from .policy import ClipFeatures, passes

Key = tuple[bool, float, float, float]
Move = Callable[[GateConfig], list[GateConfig]]

THRESHOLD_GRID = tuple(round(0.3 + 0.05 * i, 2) for i in range(13))  # 0.30 .. 0.90
MAX_THRESHOLD_SHIFT = 0.25
WEIGHT_MULTIPLIERS = (0.25, 0.5, 1.0, 1.5, 2.0)
OVERALL_GRID = tuple(round(0.5 + 0.025 * i, 3) for i in range(15))  # 0.50 .. 0.85
MAX_MEDIUM_GRID = (1, 2, 3, 4, 5)
NEVER_HARD: frozenset[str] = frozenset({"camera_adherence"})


@dataclass(frozen=True)
class Objective:
    """Calibration target on kids-draft acceptable: precision floor or F-beta."""

    mode: Literal["floor", "fbeta"] = "fbeta"
    min_precision: float = 0.8
    beta: float = 0.5


def predict(feats: Sequence[ClipFeatures], cfg: GateConfig) -> list[bool]:
    """Gate verdict per clip under `cfg`."""
    return [passes(f, cfg) for f in feats]


def kids_strict(
    pred: Sequence[bool], golds: Sequence[GoldenLabel]
) -> tuple[BinaryMetrics, BinaryMetrics]:
    """(kids-draft, strict) pass metrics for a prediction vector."""
    return (
        binary(pred, [g.kids_ok for g in golds]),
        binary(pred, [g.overall_pass for g in golds]),
    )


def fbeta(m: BinaryMetrics, beta: float) -> float:
    """F-beta of the pass class (0.0 without true positives)."""
    if not m.tp:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * m.precision * m.recall / (b2 * m.precision + m.recall)


def objective_key(
    pred: Sequence[bool], golds: Sequence[GoldenLabel], obj: Objective
) -> Key:
    """Lexicographic key for `obj.mode` (larger is better)."""
    kids, strict = kids_strict(pred, golds)
    if obj.mode == "fbeta":
        return (True, round(fbeta(kids, obj.beta), 9), strict.f1, kids.accuracy)
    feasible = kids.tp > 0 and kids.precision >= obj.min_precision
    primary = kids.recall if feasible else (kids.precision if kids.tp else 0.0)
    return (feasible, primary, strict.f1, kids.f1)


def _with_dim(cfg: GateConfig, dim: str, **update: float | bool) -> GateConfig:
    dims = dict(cfg.dimensions)
    dims[dim] = cfg.for_dimension(dim).model_copy(update=update)  # type: ignore[index,arg-type]
    return cfg.model_copy(update={"dimensions": dims})


def _gate_move(dim: str, base: GateConfig) -> Move:
    default_thr = base.for_dimension(dim).threshold  # type: ignore[arg-type]
    grid = [t for t in THRESHOLD_GRID if abs(t - default_thr) <= MAX_THRESHOLD_SHIFT]

    def move(cfg: GateConfig) -> list[GateConfig]:
        off = [_with_dim(cfg, dim, hard_gate=False)]
        return off + [_with_dim(cfg, dim, hard_gate=True, threshold=t) for t in grid]

    return move


def _demote_move(dim: str) -> Move:
    def move(cfg: GateConfig) -> list[GateConfig]:
        return [_with_dim(cfg, dim, demote_high_defects=v) for v in (False, True)]

    return move


def _weight_move(dim: str, base: GateConfig) -> Move:
    default_w = base.for_dimension(dim).weight  # type: ignore[arg-type]

    def move(cfg: GateConfig) -> list[GateConfig]:
        return [
            _with_dim(cfg, dim, weight=round(default_w * m, 4))
            for m in WEIGHT_MULTIPLIERS
        ]

    return move


def _global_moves() -> list[Move]:
    def overall(cfg: GateConfig) -> list[GateConfig]:
        return [cfg.model_copy(update={"overall_threshold": t}) for t in OVERALL_GRID]

    def medium(cfg: GateConfig) -> list[GateConfig]:
        return [
            cfg.model_copy(update={"max_medium_defects": n}) for n in MAX_MEDIUM_GRID
        ]

    return [overall, medium]


def moves(base: GateConfig, dims: Sequence[DimensionName]) -> list[Move]:
    """All coordinate moves; grids are anchored on `base` (caps relative to base values)."""
    out: list[Move] = _global_moves()
    for dim in dims:
        if dim not in NEVER_HARD:
            out.append(_gate_move(dim, base))
        out.append(_demote_move(dim))
        out.append(_weight_move(dim, base))
    return out


def fit(
    feats: Sequence[ClipFeatures],
    golds: Sequence[GoldenLabel],
    base: GateConfig,
    obj: Objective,
    sweeps: int = 3,
) -> GateConfig:
    """Coordinate descent from `base`; returns the best config found on (feats, golds)."""
    dims = sorted({d for f in feats for d in f.scores})
    cfg, best = base, objective_key(predict(feats, base), golds, obj)
    all_moves = moves(base, dims)  # type: ignore[arg-type]
    for _ in range(sweeps):
        start = best
        for move in all_moves:
            for cand in move(cfg):
                key = objective_key(predict(feats, cand), golds, obj)
                if key > best:
                    cfg, best = cand, key
        if best == start:
            break
    return cfg


def leave_one_shot_out(
    feats: Sequence[ClipFeatures],
    golds: Sequence[GoldenLabel],
    base: GateConfig,
    obj: Objective,
) -> tuple[list[bool], dict[str, GateConfig]]:
    """Held-out verdict per clip (fit on all other shots) and each fold's fitted config."""
    pred: list[bool] = [False] * len(feats)
    fold_cfgs: dict[str, GateConfig] = {}
    for shot in sorted({f.shot_id for f in feats}):
        train = [i for i, f in enumerate(feats) if f.shot_id != shot]
        cfg = fit([feats[i] for i in train], [golds[i] for i in train], base, obj)
        fold_cfgs[shot] = cfg
        for i, f in enumerate(feats):
            if f.shot_id == shot:
                pred[i] = passes(f, cfg)
    return pred, fold_cfgs

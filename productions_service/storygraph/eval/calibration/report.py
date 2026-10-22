"""Assemble the calibration report: baseline vs calibrated agreement, held-out CV, stability."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...config import GateConfig
from ..contracts import EvalReport
from .agreement import defect_hit_rates, disagreements, overall_agreement, per_dimension
from .contracts import CachedScore, GoldenLabel
from .fixture import to_record, write_fixture
from .golden import load_golden
from .policy import ClipFeatures, features
from .scorer import load_cache
from .search import Objective, fit, kids_strict, leave_one_shot_out, predict

Row = dict[str, Any]


def join(
    cache: dict[str, CachedScore], golds: Sequence[GoldenLabel]
) -> list[tuple[CachedScore, GoldenLabel]]:
    """Golden labels with a successful engine score, in golden order."""
    return [
        (cache[g.run_id], g)
        for g in golds
        if g.run_id in cache and cache[g.run_id].report is not None
    ]


def _feats(pairs: Sequence[tuple[CachedScore, GoldenLabel]]) -> list[ClipFeatures]:
    return [features(s.run_id, s.shot_id, s.report) for s, _g in pairs if s.report]


def _gate_table(cfg: GateConfig) -> Row:
    dims = {
        d: cfg.for_dimension(d).model_dump()  # type: ignore[arg-type]
        for d in sorted(cfg.dimensions)
    }
    return {
        "overall_threshold": cfg.overall_threshold,
        "min_confidence": cfg.min_confidence,
        "max_medium_defects": cfg.max_medium_defects,
        "dimensions": dims,
    }


def stability(folds: dict[str, GateConfig]) -> Row:
    """How consistently each fold chose hard gates / thresholds (low = overfit-prone)."""
    cfgs = list(folds.values())
    dims = sorted({d for c in cfgs for d in c.dimensions})
    per_dim = {}
    for d in dims:
        gates = [c.for_dimension(d) for c in cfgs]  # type: ignore[arg-type]
        hard = [g.threshold for g in gates if g.hard_gate]
        per_dim[d] = {
            "hard_share": round(len(hard) / len(gates), 2),
            "median_threshold": statistics.median(hard) if hard else None,
            "median_weight": statistics.median(g.weight for g in gates),
        }
    return {
        "overall_threshold": sorted(c.overall_threshold for c in cfgs),
        "max_medium_defects": sorted(c.max_medium_defects for c in cfgs),
        "dimensions": per_dim,
    }


def _section(
    feats: list[ClipFeatures],
    golds: list[GoldenLabel],
    cfg: GateConfig,
    reports: list[EvalReport],
) -> Row:
    return {
        "gate": _gate_table(cfg),
        "agreement": overall_agreement(feats, golds, cfg),
        "per_dimension": per_dimension(feats, golds, cfg),
        "defect_hits": defect_hit_rates(reports, golds, cfg),
        "disagreements": disagreements(feats, golds, cfg, predict(feats, cfg)),
    }


def build_report(
    cache_path: Path,
    version: str,
    base: GateConfig,
    fixture: Path | None = None,
    obj: Objective | None = None,
) -> Row:
    """Calibration report: `base` (pre-calibration gate) vs the gate fitted on golden `version`."""
    objective = obj or Objective()
    pairs = join(load_cache(cache_path), load_golden(version))
    golds = [g for _s, g in pairs]
    reports = [s.report for s, _g in pairs if s.report]
    feats = _feats(pairs)
    held_pred, folds = leave_one_shot_out(feats, golds, base, objective)
    floor_pred, _ = leave_one_shot_out(feats, golds, base, Objective(mode="floor"))
    tuned = fit(feats, golds, base, objective)
    if fixture:
        write_fixture(fixture, [to_record(s, g) for s, g in pairs])
    baseline, calibrated = (
        _section(feats, golds, base, reports),
        _section(feats, golds, tuned, reports),
    )
    return {
        "golden_version": version,
        "objective": asdict(objective),
        "n_clips": len(pairs),
        "n_shots": len({g.shot_id for g in golds}),
        "headline": {
            "baseline": baseline["agreement"],
            "calibrated_in_sample": calibrated["agreement"],
            "calibrated_held_out_loso": _held(held_pred, golds),
            "floor_objective_held_out_loso": _held(floor_pred, golds),
        },
        "baseline": baseline,
        "calibrated": calibrated,
        "fold_stability": stability(folds),
    }


def _held(pred: list[bool], golds: list[GoldenLabel]) -> Row:
    kids, strict = kids_strict(pred, golds)
    return {"kids": kids.summary(), "strict": strict.summary()}

"""Engine-vs-golden agreement: overall pass metrics, per-dimension agreement, defect hit rates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from ...config import GateConfig
from ..contracts import EvalReport
from .contracts import GoldenLabel
from .metrics import binary, spearman
from .policy import ClipFeatures, defect_counts, hard_gate_failures, overall
from .search import kids_strict, predict

Row = dict[str, Any]


def overall_agreement(
    feats: Sequence[ClipFeatures], golds: Sequence[GoldenLabel], cfg: GateConfig
) -> Row:
    """Pass/fail metrics vs kids-draft acceptable and vs strict overall pass."""
    pred = predict(feats, cfg)
    kids, strict = kids_strict(pred, golds)
    return {
        "engine_pass_rate": round(sum(pred) / len(pred), 3) if pred else 0.0,
        "kids": kids.summary(),
        "strict": strict.summary(),
    }


def _dim_row(
    dim: str,
    pairs: list[tuple[float, float, GoldenLabel]],
    cfg: GateConfig,
) -> Row:
    thr = cfg.for_dimension(dim).threshold  # type: ignore[arg-type]
    eng = [s for s, _c, _g in pairs]
    gold = [float(g.dims[dim].score) for _s, _c, g in pairs]
    conf = binary([s >= thr for s in eng], [g.dims[dim].passed for *_x, g in pairs])
    return {
        "dimension": dim,
        "n": len(pairs),
        "spearman": spearman(eng, gold),
        "mean_engine": round(sum(eng) / len(eng), 3) if eng else None,
        "mean_conf": round(sum(c for _s, c, _g in pairs) / len(pairs), 3)
        if pairs
        else None,
        "golden_fail_rate": round(
            sum(not g.dims[dim].passed for *_x, g in pairs) / len(pairs), 3
        )
        if pairs
        else None,
        "pass_confusion": conf.summary(),
    }


def per_dimension(
    feats: Sequence[ClipFeatures], golds: Sequence[GoldenLabel], cfg: GateConfig
) -> list[Row]:
    """Spearman(engine score, golden 1-5) and dimension pass confusion (n/a dims skipped)."""
    pairs: dict[str, list[tuple[float, float, GoldenLabel]]] = defaultdict(list)
    for f, g in zip(feats, golds, strict=True):
        for dim, (score, conf) in f.scores.items():
            gd = g.dims.get(dim)
            if gd is not None and not gd.na:
                pairs[dim].append((score, conf, g))
    return [_dim_row(d, pairs[d], cfg) for d in sorted(pairs)]


def _engine_flags(report: EvalReport, cfg: GateConfig) -> dict[str, bool]:
    """Dimension flagged by the engine: any medium/high defect or score below threshold."""
    out: dict[str, bool] = {}
    for dim, res in report.results.items():
        severe = any(d.severity in ("medium", "high") for d in res.defects)
        out[dim] = severe or res.score < cfg.for_dimension(dim).threshold  # type: ignore[arg-type]
    return out


def defect_hit_rates(
    reports: Sequence[EvalReport], golds: Sequence[GoldenLabel], cfg: GateConfig
) -> list[Row]:
    """Per golden tag (med+ severity): share of tagged clips the engine flags in that dimension."""
    hits: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for rep, g in zip(reports, golds, strict=True):
        flags = _engine_flags(rep, cfg)
        for dim, gd in g.dims.items():
            for tag, sev in zip(gd.tags, gd.severities, strict=True):
                if sev in ("med", "high", "blocker"):
                    hits[(dim, tag)].append(flags.get(dim, False))
    rows = [
        {"dimension": d, "tag": t, "n": len(v), "hit_rate": round(sum(v) / len(v), 3)}
        for (d, t), v in hits.items()
    ]
    return sorted(rows, key=lambda r: (-r["n"], r["tag"]))


def disagreements(
    feats: Sequence[ClipFeatures],
    golds: Sequence[GoldenLabel],
    cfg: GateConfig,
    pred: Sequence[bool],
) -> list[Row]:
    """Clips where the verdict differs from kids-draft acceptable, with the gate's reasons."""
    out: list[Row] = []
    for f, g, p in zip(feats, golds, pred, strict=True):
        if p == g.kids_ok:
            continue
        failing = [d for d, gd in g.dims.items() if gd.score <= 2]
        high, medium = defect_counts(f, cfg)
        out.append(
            {
                "run_id": f.run_id,
                "engine_pass": p,
                "kids_ok": g.kids_ok,
                "strict_pass": g.overall_pass,
                "overall": overall(f, cfg),
                "hard_gate_failures": hard_gate_failures(f, cfg),
                "n_high": high,
                "n_medium": medium,
                "golden_dims_le2": failing,
            }
        )
    return out

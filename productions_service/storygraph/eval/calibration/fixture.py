"""Compact, checked-in fixture of cached engine scores joined with golden verdicts.

Keeps only what the gate and agreement metrics read (per-dimension score, confidence, defect
type/severity; golden pass flags and 1-5 scores), so regression tests run offline in ms.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...schema import QADefect
from ..contracts import DimensionResult, EvalReport
from .contracts import CachedScore, GoldenDimension, GoldenLabel


def _dim_record(res: DimensionResult, gold: GoldenDimension | None) -> dict[str, Any]:
    return {
        "score": res.score,
        "confidence": res.confidence,
        "defects": [[d.type, d.severity] for d in res.defects],
        "golden": None
        if gold is None
        else {"score": gold.score, "pass": gold.passed, "na": gold.na},
    }


def to_record(score: CachedScore, gold: GoldenLabel) -> dict[str, Any]:
    """One fixture line for a scored clip and its golden label."""
    if score.report is None:
        raise ValueError(f"{score.run_id} has no engine report")
    return {
        "run_id": score.run_id,
        "shot_id": score.shot_id,
        "kids_ok": gold.kids_ok,
        "overall_pass": gold.overall_pass,
        "dims": {
            k: _dim_record(r, gold.dims.get(k)) for k, r in score.report.results.items()
        },
    }


def write_fixture(path: Path, records: list[dict[str, Any]]) -> None:
    """Write fixture JSONL (stable key order for reviewable diffs)."""
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(dims: dict[str, Any]) -> EvalReport:
    results = {
        k: DimensionResult(
            dimension=k,  # type: ignore[arg-type]
            score=v["score"],
            confidence=v["confidence"],
            defects=[QADefect(type=t, severity=s, evidence=t) for t, s in v["defects"]],
        )
        for k, v in dims.items()
    }
    return EvalReport(results=results)


def _golden(rec: dict[str, Any]) -> GoldenLabel:
    dims = {
        k: GoldenDimension(score=g["score"], passed=g["pass"], na=g["na"])
        for k, v in rec["dims"].items()
        if (g := v["golden"]) is not None
    }
    return GoldenLabel(
        run_id=rec["run_id"],
        shot_id=rec["shot_id"],
        overall_pass=rec["overall_pass"],
        kids_ok=rec["kids_ok"],
        dims=dims,
    )


def load_fixture(path: Path) -> list[tuple[CachedScore, GoldenLabel]]:
    """Fixture lines -> (cached engine score, golden label) pairs."""
    out: list[tuple[CachedScore, GoldenLabel]] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        rec = json.loads(ln)
        score = CachedScore(
            run_id=rec["run_id"], shot_id=rec["shot_id"], report=_report(rec["dims"])
        )
        out.append((score, _golden(rec)))
    return out

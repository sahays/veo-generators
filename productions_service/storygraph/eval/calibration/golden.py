"""Load golden-set labels (`eval_data/golden/<version>/labels.jsonl`) into typed records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import GoldenDimension, GoldenLabel

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "eval_data" / "golden"


def _dimension(raw: dict[str, Any]) -> GoldenDimension:
    defects = raw.get("defects") or []
    return GoldenDimension(
        score=int(raw["score"]),
        passed=bool(raw["pass"]),
        na=bool(raw.get("na", False)),
        tags=[str(d["tag"]) for d in defects],
        severities=[str(d.get("severity", "")) for d in defects],
    )


def parse_label(raw: dict[str, Any]) -> GoldenLabel:
    """One `labels.jsonl` record -> `GoldenLabel` (only the fields calibration needs)."""
    overall = raw["overall"]
    return GoldenLabel(
        run_id=raw["run_id"],
        shot_id=raw["shot_id"],
        overall_pass=bool(overall["pass"]),
        kids_ok=bool(overall["kids_draft_acceptable"]),
        borderline=bool(overall.get("borderline", False)),
        dims={k: _dimension(v) for k, v in raw["dimensions"].items()},
    )


def load_golden(version: str = "v1", path: Path | None = None) -> list[GoldenLabel]:
    """All golden labels of `version` (or of an explicit `labels.jsonl` path)."""
    target = path or GOLDEN_DIR / version / "labels.jsonl"
    lines = target.read_text(encoding="utf-8").splitlines()
    return [parse_label(json.loads(ln)) for ln in lines if ln.strip()]

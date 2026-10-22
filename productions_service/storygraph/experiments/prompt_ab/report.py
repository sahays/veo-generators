"""Aggregate scores.jsonl into markdown: per-variant x per-dimension means, paired deltas vs V1.

Cases (not renders) are the unit for paired comparisons: each variant's score is first
averaged over its samples within a case, then the per-case delta vs V1 is summarised with a
seeded percentile bootstrap (small-n honest: 8 cases -> wide intervals).
"""

from __future__ import annotations

import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev

from .contracts import ALL_VARIANTS, ShotCase

logger = logging.getLogger(__name__)
BOOTSTRAP_ITERS = 4000
DIM_ORDER = (
    "action_adherence.eval",
    "action.frames",
    "object_permanence.eval",
    "objects.frames",
    "character_consistency.eval",
    "character.frames",
    "camera_adherence.eval",
    "camera.frames",
    "temporal_consistency.eval",
    "cuts.ffmpeg",
    "cuts.judge",
    "script_adherence.eval",
    "dialogue.transcript",
    "overall",
    "gate_passed",
)
CaseTable = dict[str, dict[str, dict[str, float]]]  # dim -> variant -> case -> score


def load_scores(out: Path) -> list[dict]:
    path = out / "scores.jsonl"
    return [
        json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln
    ]


def _values(row: dict) -> dict[str, float | None]:
    return {
        **row["dims"],
        "overall": row["overall"],
        "gate_passed": float(row["gate_passed"]),
    }


def case_table(rows: list[dict]) -> CaseTable:
    acc: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        for dim, val in _values(row).items():
            if val is not None:
                acc[(dim, row["variant"], row["case_id"])].append(float(val))
    table: CaseTable = defaultdict(lambda: defaultdict(dict))
    for (dim, var, case), vals in acc.items():
        table[dim][var][case] = mean(vals)
    return table


def bootstrap_ci(deltas: list[float], seed: int = 0) -> tuple[float, float]:
    if len(deltas) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    stats = sorted(
        mean(rng.choices(deltas, k=len(deltas))) for _ in range(BOOTSTRAP_ITERS)
    )
    return stats[int(0.025 * BOOTSTRAP_ITERS)], stats[int(0.975 * BOOTSTRAP_ITERS) - 1]


def _cell(by_case: dict[str, float]) -> str:
    vals = list(by_case.values())
    return f"{mean(vals):.2f} ±{pstdev(vals):.2f}" if vals else "–"


def _delta_cell(var_cases: dict[str, float], base: dict[str, float]) -> str:
    common = sorted(set(var_cases) & set(base))
    if not common:
        return "–"
    deltas = [var_cases[c] - base[c] for c in common]
    lo, hi = bootstrap_ci(deltas)
    wins = sum(d > 0 for d in deltas)
    losses = sum(d < 0 for d in deltas)
    return f"{mean(deltas):+.2f} [{lo:+.2f},{hi:+.2f}] {wins}W/{losses}L"


def main_table(table: CaseTable) -> list[str]:
    head = "| dimension | " + " | ".join(ALL_VARIANTS) + " |"
    rows = [head, "|" + "---|" * (len(ALL_VARIANTS) + 1)]
    for dim in DIM_ORDER:
        cells = [_cell(table[dim].get(v, {})) for v in ALL_VARIANTS]
        rows.append(f"| {dim} | " + " | ".join(cells) + " |")
    return rows


def delta_table(table: CaseTable) -> list[str]:
    others = ALL_VARIANTS[1:]
    rows = ["| dimension | " + " | ".join(f"{v} − V1" for v in others) + " |"]
    rows.append("|" + "---|" * (len(others) + 1))
    for dim in DIM_ORDER:
        base = table[dim].get("V1_json", {})
        cells = [_delta_cell(table[dim].get(v, {}), base) for v in others]
        rows.append(f"| {dim} | " + " | ".join(cells) + " |")
    return rows


def per_case_table(table: CaseTable, cases: list[ShotCase], dim: str) -> list[str]:
    rows = [f"| case ({dim}) | category | " + " | ".join(ALL_VARIANTS) + " |"]
    rows.append("|" + "---|" * (len(ALL_VARIANTS) + 2))
    for c in cases:
        cells = [
            f"{table[dim].get(v, {}).get(c.case_id, float('nan')):.2f}"
            for v in ALL_VARIANTS
        ]
        rows.append(
            f"| {c.case_id} ({c.shot_id}) | {c.category} | " + " | ".join(cells) + " |"
        )
    return rows


def write_report(cases: list[ShotCase], out: Path, md_path: Path) -> None:
    table = case_table(load_scores(out))
    parts = [
        "## Means over cases (±sd)",
        *main_table(table),
        "",
        "## Paired delta vs V1 (mean [95% bootstrap CI] wins/losses over cases)",
        *delta_table(table),
        "",
    ]
    for dim in ("overall", "action.frames", "objects.frames", "cuts.ffmpeg"):
        parts += [f"## Per case: {dim}", *per_case_table(table, cases, dim), ""]
    md_path.write_text("\n".join(parts), encoding="utf-8")
    logger.info(
        "prompt_ab report written",
        extra={
            "who": "storygraph.experiments.prompt_ab",
            "where": "report.write_report",
            "what": "report_md_written",
            "when": "after_scoring",
            "why": "prompt format A/B",
            "how": f"{len(cases)} cases -> {md_path}",
        },
    )

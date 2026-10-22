"""Calibration CLI: `python -m storygraph.eval.calibration {score,report} ...`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ...config import Config
from .scorer import build_live_engine, read_jobs, score_jobs


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.eval.calibration")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score", help="Re-score golden clips with the live engine.")
    s.add_argument("--jobs", required=True, type=Path, help="ScoreJob JSONL manifest.")
    s.add_argument("--cache", required=True, type=Path, help="CachedScore JSONL cache.")
    s.add_argument("--workers", type=int, default=6)
    s.add_argument("--config", help="Config YAML (defaults to storygraph default).")
    r = sub.add_parser("report", help="Agreement + calibration search from the cache.")
    r.add_argument("--cache", required=True, type=Path)
    r.add_argument("--golden", default="v1", help="Golden set version.")
    r.add_argument("--out", required=True, type=Path, help="Report JSON output path.")
    r.add_argument("--fixture", type=Path, help="Optional compact fixture output path.")
    r.add_argument(
        "--base-config",
        help="YAML holding the pre-calibration `eval:` gate (baseline).",
    )
    return p.parse_args(argv)


def _score(args: argparse.Namespace) -> int:
    engine = build_live_engine(Config.load(args.config))
    merged = score_jobs(read_jobs(args.jobs), engine, args.cache, args.workers)
    failed = sorted(k for k, v in merged.items() if v.report is None)
    sys.stdout.write(json.dumps({"scored": len(merged), "failed": failed}) + "\n")
    return 1 if failed else 0


def _report(args: argparse.Namespace) -> int:
    from .report import build_report  # local: keeps `score` free of search deps

    base = Config.load(args.base_config).eval
    out = build_report(args.cache, args.golden, base, args.fixture)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    sys.stdout.write(json.dumps(out["headline"], indent=1) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse(argv)
    return _score(args) if args.cmd == "score" else _report(args)


if __name__ == "__main__":
    raise SystemExit(main())

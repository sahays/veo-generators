"""CLI: `python -m storygraph.experiments.prompt_ab <prompts|render|score|report> ...`.

prompts  write every variant's prompt + primary request text for each case (no network)
render   render cases x variants x samples via the production Omni adapter (resumable)
score    eval-engine + ffmpeg frame checks for every successful render
report   aggregate scores.jsonl into a markdown table
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from .contracts import ALL_VARIANTS, ShotCase, VariantId
from .runner import Job, MatrixRunner, build_prompt, make_package, primary_request

MAX_RENDERS = 48
logger = logging.getLogger("storygraph.experiments.prompt_ab")


def load_cases(path: Path) -> list[ShotCase]:
    return [ShotCase.from_dict(c) for c in json.loads(path.read_text(encoding="utf-8"))]


def _variants(raw: str) -> list[VariantId]:
    wanted = [v for v in ALL_VARIANTS if v in raw.split(",")] if raw else []
    return wanted or list(ALL_VARIANTS)


def _project(args: argparse.Namespace) -> str:
    return args.project or os.getenv("GOOGLE_CLOUD_PROJECT", "")


def cmd_prompts(cases: list[ShotCase], out: Path) -> None:
    pdir = out / "prompts"
    pdir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for variant in ALL_VARIANTS:
            pv = build_prompt(case, variant)
            text, uris = primary_request(make_package(case, pv.prompt, 0))
            (pdir / f"{case.case_id}__{variant}.txt").write_text(text, encoding="utf-8")
            logger.info(
                "prompt_ab prompt who=cli what=%s/%s words=%d images=%d why=dry_run",
                case.case_id,
                variant,
                pv.words,
                len(uris),
            )


def cmd_render(cases: list[ShotCase], out: Path, args: argparse.Namespace) -> None:
    extra = _variants(args.extra_variants) if args.extra_variants else []
    jobs = [
        Job(case, variant, sample)
        for sample in range(args.samples + (1 if extra else 0))
        for case in cases
        for variant in (_variants(args.variants) if sample < args.samples else extra)
    ]
    if len(jobs) > MAX_RENDERS:
        raise SystemExit(
            f"{len(jobs)} renders exceeds the {MAX_RENDERS}-render budget cap"
        )
    recs = MatrixRunner(out, _project(args), args.workers).run(jobs)
    cost = sum(r.est_cost_usd for r in recs)
    logger.info(
        "prompt_ab render_batch who=cli what=renders ok=%d/%d est_cost_usd<=%.2f why=ab_experiment",
        sum(r.ok for r in recs),
        len(recs),
        cost,
    )


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.experiments.prompt_ab")
    p.add_argument("command", choices=["prompts", "render", "score", "report"])
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--variants", default="")
    p.add_argument("--samples", type=int, default=2)
    p.add_argument(
        "--extra-variants", default="", help="Variants that get one more sample."
    )
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--project", default="")
    p.add_argument("--report-md", type=Path)
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = _parse()
    cases = load_cases(args.cases)
    if args.command == "prompts":
        cmd_prompts(cases, args.out)
    elif args.command == "render":
        cmd_render(cases, args.out, args)
    elif args.command == "score":
        from .scorer import score_all

        score_all(cases, args.out, args.workers, _project(args))
    else:
        from .report import write_report

        write_report(cases, args.out, args.report_md or args.out / "report.md")


if __name__ == "__main__":
    main()

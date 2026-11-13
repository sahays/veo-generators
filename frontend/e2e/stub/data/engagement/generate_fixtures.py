"""Generate the Engagement fixtures served by the browser-test stub API.

Regenerate (from anywhere; needs `node` >= 22.18 and the API virtualenv):

    api/venv/bin/python frontend/e2e/stub/data/engagement/generate_fixtures.py

Every number in the fixtures is computed by the real engagement maths in
`api/engagement_signals` (the code the worker runs), from the kit's ad-spot
timeline (`frontend/src/types/timeline/__tests__/adSpotFixture.ts`), so the
reports cannot drift from the backend or from the fixture video.

Inputs, checked in next to this file and edited by hand:

    barc-kadak-chai-monsoon.csv   BARC export, one row per half second, 5 s lead-in
    unmappable-notes.csv          a CSV whose columns cannot be mapped
    prose.json                    the titles, explanations and recommendations
                                  the language model would have written

Outputs, never edited by hand:

    templates.json                              `GET /engagement/templates`
    previews.json                               `SignalPreview` per input CSV
    reports/template-<id>.json                  one report per built-in template
    reports/template-jumpy-no-prose.json        the jumpy report with empty prose
    reports/barc.json                           the report of the BARC CSV
    signal-notes.json                           parser warnings the worker would
                                                note on the BARC job's record

The run fails (non-zero exit, nothing reported as written) when `prose.json`
cites an extremum id, influence key or segment id that a report does not have,
or leaves an extremum of a prose-carrying report without prose. After a change
to the maths, read the digest this script prints and rewrite the prose to match.
No network or cloud access; output is byte-identical from run to run.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "api"))

# Imported by name after the path is set up: `api/` is not a package, and its
# `sitecustomize` puts the flat module names of `api/engagement_signals` on sys.path.
importlib.import_module("sitecustomize")
report_builder = importlib.import_module("report_builder")
signal_parser = importlib.import_module("signal_parser")
signal_templates = importlib.import_module("signal_templates")

TIMELINE_MODULE = REPO / "frontend/src/types/timeline/__tests__/adSpotFixture.ts"
REPORTS_DIR = HERE / "reports"
BARC_CSV = "barc-kadak-chai-monsoon.csv"
UNMAPPABLE_CSV = "unmappable-notes.csv"
BARC_OFFSET_SEC = -5.0
# As `MAX_SIGNAL_NOTES` in `workers/insight_jobs/engagement_processor.py`.
MAX_SIGNAL_NOTES = 3
DEFAULT_SEED = "eng-stub"
# Seeded stub records (see `engagementState.ts`): the worker seeds a template
# curve with the record id, so these reports are the ones those records get.
SEED_BY_TEMPLATE: dict[str, str] = {
    "jumpy": "eng-fixture-template",
    "slow_burn": "eng-fixture-running",
    "high": "eng-fixture-waiting",
}
PROSE_REPORTS: tuple[str, ...] = ("template-jumpy", "barc")
NO_PROSE_SOURCE = "template-jumpy"
NO_PROSE_REPORT = "template-jumpy-no-prose"
_PRINT_TIMELINE = (
    "const m = await import(process.argv[1]);"
    "process.stdout.write(JSON.stringify(m.AD_SPOT_TIMELINE));"
)

Report = dict[str, Any]


class ParsedSeries(Protocol):
    """The part of `engagement_series.SignalSeries` this script reads itself."""

    warnings: list[str]


class ProseError(ValueError):
    """`prose.json` does not match the report it is written for."""


def load_timeline() -> dict[str, Any]:
    """The ad-spot `TimelineDoc`, read from the TypeScript fixture with node."""
    command = [
        "node",
        "--disable-warning=MODULE_TYPELESS_PACKAGE_JSON",
        "--input-type=module",
        "--eval",
        _PRINT_TIMELINE,
        TIMELINE_MODULE.as_uri(),
    ]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"node could not load the timeline: {done.stderr.strip()}")
    timeline = json.loads(done.stdout)
    if not isinstance(timeline, dict) or not timeline.get("segments"):
        raise RuntimeError("AD_SPOT_TIMELINE is not a timeline document")
    return timeline


def write_json(path: Path, payload: object) -> None:
    """Write `payload` as stable, human-readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False, ensure_ascii=False)
        handle.write("\n")


def template_report(timeline: dict[str, Any], template: dict[str, Any]) -> Report:
    """The deterministic report of one built-in template on the ad spot."""
    ident = template["id"]
    seed = SEED_BY_TEMPLATE.get(ident, DEFAULT_SEED)
    series = signal_templates.generate_template_series(
        ident, timeline["duration_sec"], seed=seed
    )
    meta = {
        "kind": "template",
        "template_id": ident,
        "label": template["label"],
        "offset_sec": 0,
    }
    return report_builder.build_report_core(timeline, series, meta)


def barc_series() -> ParsedSeries:
    """The BARC CSV as the worker parses it, aligned past its lead-in rows."""
    content = (HERE / BARC_CSV).read_bytes()
    return signal_parser.parse_signal_csv(
        content, None, None, offset_sec=BARC_OFFSET_SEC
    )


def barc_report(timeline: dict[str, Any], series: ParsedSeries) -> Report:
    """The deterministic report of the parsed BARC series."""
    meta = {"kind": "barc", "label": BARC_CSV, "offset_sec": BARC_OFFSET_SEC}
    return report_builder.build_report_core(timeline, series, meta)


def _unknown(cited: list[Any], known: set[str]) -> list[str]:
    """The cited references a report does not contain, in citation order."""
    return [str(ref) for ref in cited if ref not in known]


def _action_problems(report: Report, payload: dict[str, Any]) -> list[str]:
    """Problems with the influence keys cited by `do_more` / `do_less`."""
    influence = {entry["key"]: entry for entry in report["influence"]}
    problems: list[str] = []
    for name, sign in (("do_more", 1), ("do_less", -1)):
        keys = [item.get("key") for item in payload.get(name, [])]
        missing = _unknown(keys, set(influence))
        if missing:
            problems.append(f"{name} cites unknown influence keys {missing}")
        wrong = [k for k in keys if k in influence and _misused(influence[k], sign)]
        if wrong:
            problems.append(f"{name} cites weak or opposite influence {wrong}")
    return problems


def _misused(entry: dict[str, Any], sign: int) -> bool:
    """True for an influence entry the recommendation prompt would not offer."""
    return bool(entry["low_support"]) or entry["delta_pct"] * sign <= 0


def prose_problems(report: Report, prose: dict[str, Any]) -> list[str]:
    """Everything that would make prose silently vanish from the report."""
    extrema = {extremum["id"] for extremum in report["extrema"]}
    explained = [item.get("id") for item in prose.get("explanations", [])]
    payload = prose.get("recommendations", {})
    problems: list[str] = []
    missing = _unknown(explained, extrema)
    if missing:
        problems.append(f"explanations cite unknown extrema {missing}")
    bare = sorted(extrema - set(explained))
    if bare:
        problems.append(f"extrema without an explanation: {bare}")
    problems += _action_problems(report, payload)
    segments = {stat["segment_id"] for stat in report["segments"]}
    fixed = [item.get("segment_id") for item in payload.get("segment_fixes", [])]
    missing = _unknown(fixed, segments)
    if missing:
        problems.append(f"segment_fixes cite unknown segments {missing}")
    return problems


def _lost_prose(report: Report, prose: dict[str, Any]) -> list[str]:
    """Prose that the binding step dropped or emptied (checked after applying)."""
    payload = prose.get("recommendations", {})
    bound = report["recommendations"]
    lost = [
        f"{name}: {len(payload.get(name, []))} written, {len(bound[name])} bound"
        for name in ("do_more", "do_less", "segment_fixes")
        if len(payload.get(name, [])) != len(bound[name])
    ]
    lost += [
        f"{e['id']} has an empty title or explanation"
        for e in report["extrema"]
        if not (e["title"] and e["explanation"])
    ]
    if not bound["headline"]:
        lost.append("recommendations.headline is empty")
    return lost


def with_prose(
    name: str, report: Report, prose: dict[str, Any], timeline: dict[str, Any]
) -> Report:
    """`report` with the hand-written prose bound to it; raises `ProseError`."""
    problems = prose_problems(report, prose)
    if not problems:
        report = report_builder.apply_explanations(report, prose["explanations"])
        report = report_builder.apply_recommendations(
            report, prose["recommendations"], timeline
        )
        problems = _lost_prose(report, prose)
    if problems:
        raise ProseError(f"prose.json [{name}]: " + "; ".join(problems))
    return report


def _digest_lines(report: Report, timeline: dict[str, Any]) -> list[str]:
    """The facts a prose writer needs, as the model prompts would present them."""
    inputs = report_builder.recommendation_inputs(report, timeline)
    lines = [f"  stats {report['stats']}", f"  kpis  {report['kpis']}"]
    lines += [
        f"  {e['id']:<9}{e['time_sec']:>6}s value={e['value']} "
        f"delta={e['delta_pct']}% prominence={e['prominence']} {e['segment_id']}"
        for e in report["extrema"]
    ]
    for label in ("top_influence", "bottom_influence"):
        lines += [
            f"  {label[:-10]:<7}{i['key']:<30} delta={i['delta_pct']}% "
            f"coverage={i['coverage_sec']}s"
            for i in inputs[label]
        ]
    lines += [
        f"  low    {s['segment_id']} avg={s['avg']} delta={s['delta_pct']}% "
        f"{s['title']}"
        for s in inputs["low_segments"]
    ]
    return lines


def print_digest(name: str, report: Report, timeline: dict[str, Any]) -> None:
    """Print the core numbers of one report (read these before editing prose)."""
    signal = report["signal"]
    head = f"{name}: {signal['primary_metric']} ({signal['point_count']} points)"
    print("\n".join([head, *_digest_lines(report, timeline)]))


def build_cores(timeline: dict[str, Any], barc: ParsedSeries) -> dict[str, Report]:
    """The deterministic report of every template and of the BARC CSV, by name."""
    cores = {
        f"template-{template['id']}": template_report(timeline, template)
        for template in signal_templates.list_templates()
    }
    cores["barc"] = barc_report(timeline, barc)
    return cores


def build_reports(timeline: dict[str, Any], barc: ParsedSeries) -> dict[str, Report]:
    """Every report file by name (without `.json`), prose applied where written.

    Prints the digest of every report before binding any prose, and raises one
    `ProseError` naming the problems of all prose-carrying reports.
    """
    reports = build_cores(timeline, barc)
    for name, core in reports.items():
        print_digest(name, core, timeline)
    prose = json.loads((HERE / "prose.json").read_text(encoding="utf-8"))
    reports[NO_PROSE_REPORT] = reports[NO_PROSE_SOURCE]
    errors: list[str] = []
    for name in PROSE_REPORTS:
        try:
            reports[name] = with_prose(name, reports[name], prose[name], timeline)
        except ProseError as err:
            errors.append(str(err))
    if errors:
        raise ProseError("\n".join(errors))
    return reports


def build_previews() -> dict[str, Any]:
    """`SignalPreview` of each input CSV, as `POST /signal-preview` returns it."""
    return {
        name: signal_parser.preview_signal_csv((HERE / name).read_bytes(), name)
        for name in (BARC_CSV, UNMAPPABLE_CSV)
    }


def main() -> int:
    """Build everything first, then write, so a failure leaves no partial set."""
    timeline = load_timeline()
    barc = barc_series()
    try:
        reports = build_reports(timeline, barc)
    except ProseError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    write_json(HERE / "templates.json", signal_templates.list_templates())
    write_json(HERE / "previews.json", build_previews())
    notes = {"barc": list(barc.warnings[:MAX_SIGNAL_NOTES])}
    write_json(HERE / "signal-notes.json", notes)
    for name, report in reports.items():
        write_json(REPORTS_DIR / f"{name}.json", report)
    print(
        f"Wrote templates, previews, signal notes and {len(reports)} reports to {HERE}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

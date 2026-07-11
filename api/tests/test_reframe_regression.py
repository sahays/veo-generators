"""Replay-corpus regression gates — the anti-circling mechanism.

Replays committed production fixtures (``tests/fixtures/reframe/*.json.gz``)
through the pure pipeline (reframe_replay) and gates each quality metric
against ``baselines.json`` with direction-aware deltas. A code change that
moves a metric must move it the right way — or the change to baselines.json
becomes an explicit, reviewable part of the PR
(``python scripts/build-reframe-fixture.py --rebaseline``).

Skips cleanly when no fixtures are committed yet (the corpus is captured by
re-running reference jobs after the detections.json.gz dump ships).
"""

import gzip
import json
from pathlib import Path

import pytest

from reframe_replay import plan_metrics, replay

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "reframe"
BASELINES = FIXTURE_DIR / "baselines.json"

# metric → (rule, tolerance). Directions encode what a regression means:
# a rise in face_cut is a subject clipped; a fall in framed_active is the
# speaker lost. Metrics absent here are informational (tracked in baselines,
# never gating).
RULES = {
    "face_cut_rate": ("max_increase", 0.01),
    "over_letterbox_rate": ("max_increase", 0.0),
    "center_crop_segments": ("max_increase", 0),
    "crop_jumps_per_min": ("max_increase_pct", 0.20),
    "ar_changes_per_min": ("max_increase_pct", 0.20),
    "framed_speaker_active_rate": ("max_decrease", 0.05),
}


def _fixtures():
    if not FIXTURE_DIR.is_dir():
        return []
    return sorted(FIXTURE_DIR.glob("*.json.gz"))


def _load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _violations(job: str, current: dict, baseline: dict) -> list:
    out = []
    for metric, (rule, tol) in RULES.items():
        base, cur = baseline.get(metric), current.get(metric)
        if base is None or cur is None:
            continue  # metric not measurable on this fixture (e.g. no dialogue)
        if rule == "max_increase" and cur > base + tol:
            out.append(f"{job}: {metric} rose {base} → {cur} (allowed +{tol})")
        elif rule == "max_decrease" and cur < base - tol:
            out.append(f"{job}: {metric} fell {base} → {cur} (allowed -{tol})")
        elif rule == "max_increase_pct" and base > 0 and cur > base * (1 + tol):
            out.append(f"{job}: {metric} rose {base} → {cur} (allowed +{tol:.0%})")
        elif rule == "max_increase_pct" and base == 0 and cur > 0.5:
            out.append(f"{job}: {metric} rose 0 → {cur}")
    return out


fixtures = _fixtures()


@pytest.mark.skipif(not fixtures, reason="no committed reframe fixtures yet")
@pytest.mark.parametrize("path", fixtures, ids=lambda p: p.name.split(".")[0])
def test_fixture_within_baseline(path):
    if not BASELINES.exists():
        pytest.skip("no baselines.json — run build-reframe-fixture.py --rebaseline")
    baselines = json.loads(BASELINES.read_text())
    job = path.name.split(".")[0]
    if job not in baselines:
        pytest.fail(
            f"{job} has a fixture but no baseline — "
            "run build-reframe-fixture.py --rebaseline and review the diff"
        )
    fixture = _load(path)
    result = replay(fixture)
    current = plan_metrics(result["segments"], result["report"])
    violations = _violations(job, current, baselines[job])
    assert not violations, "metric regressions:\n" + "\n".join(violations)


@pytest.mark.skipif(not fixtures, reason="no committed reframe fixtures yet")
@pytest.mark.parametrize("path", fixtures, ids=lambda p: p.name.split(".")[0])
def test_fixture_replay_is_deterministic(path):
    """Two replays of the same inputs must agree — guards against nondeterminism
    (set iteration, unseeded randomness) silently entering the planner."""
    fixture = _load(path)
    a = replay(fixture)
    b = replay(fixture)
    assert plan_metrics(a["segments"], a["report"]) == plan_metrics(
        b["segments"], b["report"]
    )

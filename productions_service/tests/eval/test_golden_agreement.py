"""Golden-set agreement regression for the shipped eval gate (config/default.yaml `eval:`).

The fixture holds cached live-engine scores for golden v1 (see docs/eval/eval_calibration_v1.md).
Floors are the leave-one-shot-out held-out numbers of the calibration, so a gate change that
silently degrades agreement with the golden set fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from storygraph.config import Config, GateConfig
from storygraph.eval.calibration.contracts import BinaryMetrics
from storygraph.eval.calibration.fixture import load_fixture
from storygraph.eval.calibration.metrics import binary, spearman
from storygraph.eval.calibration.policy import features, passes
from storygraph.eval.gate import decide
from storygraph.qa.critic.checks import CriticThresholds

FIXTURE = Path(__file__).parent / "fixtures" / "golden_v1_engine_scores.jsonl"
BASELINE = (
    Path(__file__).resolve().parents[3]
    / "docs/eval/eval_calibration_v1/baseline_gate_v0.yaml"
)
# Leave-one-shot-out held-out kids-draft metrics of the calibrated gate (golden v1, 66 clips).
# Strict pass is not floored: golden v1 has a single strict pass, so its F1 is pure noise.
KIDS_PRECISION_FLOOR = 0.636
KIDS_RECALL_FLOOR = 0.483
KIDS_F1_FLOOR = 0.549


@pytest.fixture(scope="module")
def shipped() -> Config:
    return Config.load(None)


def _kids_metrics(cfg: GateConfig, thr: CriticThresholds) -> BinaryMetrics:
    """Kids-draft agreement of the real gate (`decide`) on the fixture."""
    pairs = load_fixture(FIXTURE)
    pred = [decide(s.report.results, cfg, thr)[0].passed for s, _g in pairs if s.report]
    return binary(pred, [g.kids_ok for _s, g in pairs])


def test_fast_policy_matches_real_gate(shipped: Config) -> None:
    """The search optimises `policy.passes`; it must equal `gate.decide` on every clip."""
    thr = CriticThresholds.from_cfg(shipped.qa)
    strict = shipped.eval.model_copy(
        update={"overall_threshold": 0.9, "max_medium_defects": 0}
    )  # exercises the defect-count and overall branches the shipped gate rarely hits
    for cfg in (shipped.eval, strict, Config.load(BASELINE).eval):
        for score, _gold in load_fixture(FIXTURE):
            assert score.report is not None
            real, _dims, _overall = decide(score.report.results, cfg, thr)
            fast = passes(features(score.run_id, score.shot_id, score.report), cfg)
            assert fast == real.passed, score.run_id


def test_shipped_gate_meets_calibrated_golden_floor(shipped: Config) -> None:
    kids = _kids_metrics(shipped.eval, CriticThresholds.from_cfg(shipped.qa))
    assert kids.precision >= KIDS_PRECISION_FLOOR, kids.summary()
    assert kids.recall >= KIDS_RECALL_FLOOR, kids.summary()
    assert kids.f1 >= KIDS_F1_FLOOR, kids.summary()


def test_pre_calibration_gate_is_below_the_floor(shipped: Config) -> None:
    """Sensitivity check: the old gate must fail the floor, or the floor guards nothing."""
    kids = _kids_metrics(
        Config.load(BASELINE).eval, CriticThresholds.from_cfg(shipped.qa)
    )
    assert kids.recall < KIDS_RECALL_FLOOR and kids.f1 < KIDS_F1_FLOOR, kids.summary()


def test_shipped_gate_never_hard_gates_camera(shipped: Config) -> None:
    assert shipped.eval.for_dimension("camera_adherence").hard_gate is False


def test_spearman_handles_ties_and_constant_input() -> None:
    # golden 1-5 scores are heavily tied; ranks must be averaged, not positional
    assert spearman([1, 2, 2, 3], [1, 2, 2, 3]) == 1.0
    assert spearman([0.9, 0.9, 0.1, 0.1], [5, 5, 1, 1]) == 1.0
    assert spearman([1.0, 0.5, 0.0], [1, 3, 5]) == -1.0
    assert spearman([1.0, 1.0, 1.0], [1, 3, 5]) is None

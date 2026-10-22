"""Evidence-based hard gate + S9 re-judging after gate changes (p-0irbygdv claymation run)."""

from __future__ import annotations

from storygraph.config import Config
from storygraph.eval.contracts import DimensionResult
from storygraph.eval.gate import decide, gate_fingerprint
from storygraph.pipeline.render_stage import _needs_qa
from storygraph.qa.critic.checks import CriticThresholds
from storygraph.schema import GenerationRun, QAReport, QADefect, Role, Status


def _decide(cfg: Config, score: float, defects: list[QADefect]) -> bool:
    res = {
        "character_consistency": DimensionResult(
            dimension="character_consistency",
            score=score,
            confidence=0.9,
            defects=defects,
        ),
        "action_adherence": DimensionResult(
            dimension="action_adherence", score=1.0, confidence=0.9
        ),
    }
    decision, _, _ = decide(res, cfg.eval, CriticThresholds.from_cfg(cfg.qa))
    return decision.passed


def _drift() -> QADefect:
    return QADefect(
        type="identity_drift",
        severity="medium",
        subject="Pip",
        evidence="t=2s eyes change",
    )


def test_near_threshold_character_score_without_defect_does_not_block(
    default_cfg: Config,
) -> None:
    """Live: 15/15 claymation clips scored 0.61-0.68 with zero identity defects."""
    assert _decide(default_cfg, 0.64, []) is True


def test_near_threshold_with_identity_defect_still_blocks(default_cfg: Config) -> None:
    assert _decide(default_cfg, 0.64, [_drift()]) is False


def test_far_below_threshold_blocks_without_defect(default_cfg: Config) -> None:
    assert _decide(default_cfg, 0.5, []) is False


def _run(status: Status, gate_version: str | None) -> GenerationRun:
    qa = QAReport(passed=status == Status.APPROVED, gate_version=gate_version)
    return GenerationRun(
        id="run_x",
        created_by=Role.PIPELINE,
        status=status,
        shot_id="shot_x",
        attempt=1,
        provider="mock",
        model="m",
        compiled_prompt="p",
        seed=1,
        package_hash="h",
        output_video_uri="gs://b/clip.mp4",
        qa_scores=qa,
    )


def test_s9_rejudges_only_failed_runs_from_an_older_gate(default_cfg: Config) -> None:
    current = gate_fingerprint(default_cfg)
    assert _needs_qa(_run(Status.FAILED, "old"), current) is True
    assert _needs_qa(_run(Status.FAILED, current), current) is False
    assert _needs_qa(_run(Status.APPROVED, "old"), current) is False


def test_gate_fingerprint_changes_with_thresholds(default_cfg: Config) -> None:
    changed = default_cfg.model_copy(deep=True)
    changed.eval.overall_threshold = 0.5
    assert gate_fingerprint(changed) != gate_fingerprint(default_cfg)

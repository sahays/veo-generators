"""Eval gate: hard gates (confidence-aware), camera never hard, config thresholds, overall."""

from __future__ import annotations

from storygraph.config import Config, DimensionGate, GateConfig
from storygraph.eval.contracts import DimensionResult
from storygraph.eval.gate import decide
from storygraph.qa.critic.checks import CriticThresholds


def _results(**scores: tuple[float, float]) -> dict[str, DimensionResult]:
    return {
        name: DimensionResult(dimension=name, score=s, confidence=c)  # type: ignore[arg-type]
        for name, (s, c) in scores.items()
    }


def _thr(cfg: Config) -> CriticThresholds:
    return CriticThresholds.from_cfg(cfg.qa)


def test_confident_hard_gate_blocks_low_confidence_does_not(
    default_cfg: Config,
) -> None:
    good = {"action_adherence": (1.0, 0.9), "scene_consistency": (1.0, 0.9)}
    blocked, _dims, _ = decide(
        _results(character_consistency=(0.5, 0.9), **good),
        default_cfg.eval,
        _thr(default_cfg),
    )
    assert not blocked.passed and blocked.failure_reasons == [
        "character_consistency 0.50 below 0.65 (hard gate)"
    ]
    unsure, _, _ = decide(
        _results(character_consistency=(0.5, 0.1), **good),
        default_cfg.eval,
        _thr(default_cfg),
    )
    assert unsure.passed


def test_camera_is_never_a_hard_gate(default_cfg: Config) -> None:
    cfg = GateConfig(
        dimensions={
            "camera_adherence": DimensionGate(
                threshold=0.9, weight=0.01, hard_gate=True
            )
        },
        overall_threshold=0.0,
    )
    decision, dims, _ = decide(
        _results(camera_adherence=(0.0, 1.0)), cfg, _thr(default_cfg)
    )
    assert decision.passed and dims[0].hard_gate is False


def test_thresholds_come_from_config(default_cfg: Config) -> None:
    results = _results(action_adherence=(0.8, 0.9))
    strict = GateConfig(
        dimensions={
            "action_adherence": DimensionGate(threshold=0.9, weight=1, hard_gate=True)
        },
        overall_threshold=0.0,
    )
    lenient = strict.model_copy(
        update={
            "dimensions": {
                "action_adherence": DimensionGate(threshold=0.7, hard_gate=True)
            }
        }
    )
    assert not decide(results, strict, _thr(default_cfg))[0].passed
    assert decide(results, lenient, _thr(default_cfg))[0].passed


def test_overall_threshold_blocks_weak_soft_dimensions(default_cfg: Config) -> None:
    weak = _results(style_consistency=(0.2, 0.9), physical_plausibility=(0.3, 0.9))
    decision, _, overall = decide(weak, default_cfg.eval, _thr(default_cfg))
    assert overall < default_cfg.eval.overall_threshold and not decision.passed
    assert decision.failure_reasons[-1].startswith("overall ")


def test_yaml_gate_matches_code_defaults() -> None:
    assert Config.load().eval == GateConfig()

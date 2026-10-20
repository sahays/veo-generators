"""Temporal dimension on synthetic ffmpeg clips: early cut (hard gate), freeze, flicker, clean."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from eval_clips import FFMPEG, SPEC, flicker_clip, moving_clip, segments_clip

from storygraph.adapters.mock import MockVLMProvider
from storygraph.config import Config
from storygraph.eval.contracts import DimensionResult, EvalInput
from storygraph.eval.engine import EvalEngine
from storygraph.eval.gate import decide
from storygraph.qa.critic.checks import CriticThresholds

pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg")


def _engine(cfg: Config) -> EvalEngine:
    return EvalEngine(
        vlm=MockVLMProvider(),
        gate_cfg=cfg.eval,
        thr=CriticThresholds.from_cfg(cfg.qa),
        run_cv=False,
    )


def _temporal(cfg: Config, clip: Path) -> tuple[DimensionResult, EvalEngine, dict]:
    engine = _engine(cfg)
    inp = EvalInput(clip_bytes=clip.read_bytes(), spec_json=json.dumps(SPEC))
    report = engine.evaluate(inp)
    return report.results["temporal_consistency"], engine, report.results


def _types(res: DimensionResult) -> dict[str, str]:
    return {d.type: d.severity for d in res.defects}


def test_early_hard_cut_fails_temporal_hard_gate(
    tmp_path: Path, default_cfg: Config
) -> None:
    clip = segments_clip(tmp_path / "cut.mp4", [("red", 1.0), ("blue", 3.0)])
    res, engine, results = _temporal(default_cfg, clip)
    assert _types(res).get("hard_cut") == "medium" and res.score < 0.6
    decision, dims, _ = decide(results, engine.gate_cfg, engine.thr)
    assert not decision.passed
    assert any(
        "temporal_consistency" in r and "hard gate" in r
        for r in decision.failure_reasons
    )
    assert not next(d for d in dims if d.dimension == "temporal_consistency").passed


def test_frozen_clip_flags_freeze(tmp_path: Path, default_cfg: Config) -> None:
    clip = segments_clip(tmp_path / "frozen.mp4", [("red", 4.0)])
    res, _, _ = _temporal(default_cfg, clip)
    assert _types(res).get("frozen_frame") == "medium"
    assert res.score < 1.0 and res.evidence[0].t_s == 0.0


def test_flicker_detected(tmp_path: Path, default_cfg: Config) -> None:
    res, _, _ = _temporal(default_cfg, flicker_clip(tmp_path / "flicker.mp4", 4.0))
    assert _types(res).get("flicker") == "medium"
    assert "frozen_frame" not in _types(res)


def test_clean_moving_clip_has_no_temporal_defects(
    tmp_path: Path, default_cfg: Config
) -> None:
    res, _, _ = _temporal(default_cfg, moving_clip(tmp_path / "ok.mp4", 4.0))
    assert res.defects == [] and res.score == 1.0 and res.confidence >= 0.9

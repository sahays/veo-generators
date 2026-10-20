"""EvalEngine: probe once, metrics once, ONE sectioned VLM call, every dimension, gate.

The S9 critic and the offline harness (`python -m storygraph.eval.run`) share this engine
unchanged. `collect` returns the raw VLM answer so callers can still grade legacy `QAReport`
responders; `grade` turns a rubric into an `EvalReport`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..adapters.base import VLMProvider
from ..adapters.embeddings import ImageEmbedder
from ..adapters.media_frames import ClipProbe, probe_clip
from ..adapters.transcribe import Transcriber
from ..qa.critic.checks import CriticThresholds, check_cuts
from ..qa.critic.rubric import ClipRubric
from ..qa.critic.spec import CriticSpec, parse_compiled_spec
from ..schema import QAReport
from .contracts import EvalInput, EvalReport, GateConfig
from .dimensions.base import EvalContext
from .dimensions.registry import all_dimensions
from .gate import overall_score
from .media import assemble_images, media_signals
from .metrics.bundle import MetricBundle, compute_metrics
from .prompt import build_eval_prompt
from .rubric import EVAL_RUBRIC_VERSION, EvalRubric, as_eval_rubric

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Collected:
    """One clip's probe, spec and raw VLM answer (rubric or legacy QAReport)."""

    probe: ClipProbe
    spec: CriticSpec
    raw: EvalRubric | QAReport


@dataclass
class EvalEngine:
    vlm: VLMProvider
    gate_cfg: GateConfig
    thr: CriticThresholds
    embedder: ImageEmbedder | None = None
    transcriber: Transcriber | None = None
    instructions: str = ""
    run_cv: bool = True
    _dims: list = field(default_factory=all_dimensions)

    def collect(self, inp: EvalInput) -> Collected:
        """Probe the clip and make the single sectioned VLM call."""
        spec = parse_compiled_spec(inp.spec_json)
        probe = probe_clip(inp.load_clip() or b"mock_mp4")
        prev = inp.prev_last_frame or None
        images, labels = assemble_images(inp.refs, prev, probe)
        prompt = build_eval_prompt(
            inp, spec, labels, prev is not None, self.instructions
        )
        raw = self.vlm.review(images=images, prompt=prompt, schema=EvalRubric)
        if isinstance(raw, ClipRubric):
            raw = as_eval_rubric(raw)
        return Collected(probe=probe, spec=spec, raw=raw)

    def context(
        self, inp: EvalInput, got: Collected, rubric: EvalRubric
    ) -> EvalContext:
        """Deterministic metrics (once) + media signals shared by every dimension."""
        metrics: MetricBundle = compute_metrics(
            inp, got.probe, self.embedder, self.transcriber
        )
        signals = media_signals(
            got.probe, inp.prev_last_frame, metrics.video, self.run_cv
        )
        return EvalContext(
            spec=got.spec, rubric=rubric, metrics=metrics, signals=signals, thr=self.thr
        )

    def grade(self, inp: EvalInput, got: Collected, rubric: EvalRubric) -> EvalReport:
        """Run every dimension against the shared context."""
        ctx = self.context(inp, got, rubric)
        results = {d.name: d.evaluate(inp, ctx) for d in self._dims}
        _, cuts = check_cuts(ctx.spec, rubric, ctx.signals, self.thr)
        report = EvalReport(
            results=results,
            overall=overall_score(results, self.gate_cfg),
            duration_s=got.probe.duration_s,
            cut_times_s=cuts,
            frames_sampled=len(got.probe.frames),
            rubric_version=EVAL_RUBRIC_VERSION,
        )
        _log_report(inp, report)
        return report

    def evaluate(self, inp: EvalInput) -> EvalReport:
        """Collect + grade (legacy QAReport answers are lifted into an empty rubric)."""
        got = self.collect(inp)
        if isinstance(got.raw, QAReport):
            raise TypeError("VLM returned a legacy QAReport; grade it via the critic")
        return self.grade(inp, got, got.raw)


def _log_report(inp: EvalInput, report: EvalReport) -> None:
    logger.info(
        "video_eval_report",
        extra={
            "who": "storygraph.eval.engine",
            "where": "EvalEngine.grade",
            "what": "clip_evaluated",
            "when": datetime.now(UTC).isoformat(),
            "why": "S9 clip QA / offline eval",
            "how": f"{report.version} over {report.frames_sampled} frames",
            "shot_id": inp.shot_id,
            "overall": report.overall,
            "scores": {k: r.score for k, r in report.results.items()},
        },
    )

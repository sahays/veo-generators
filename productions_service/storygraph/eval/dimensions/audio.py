"""Audio: speech present for speakers / absent for non-speakers, silence, clipping, loudness."""

from __future__ import annotations

from ...adapters.audio_levels import AudioLevels
from ...qa.critic.checks import defect
from ...qa.critic.gate import check_speech
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput, Evidence
from .base import EvalContext, make_result, score_from_defects

CLIP_PEAK_DB = -0.1
HOT_MEAN_DB = -8.0


def _level_defects(levels: AudioLevels | None) -> list[QADefect]:
    if levels is None:
        return []
    out: list[QADefect] = []
    if levels.max_db >= CLIP_PEAK_DB:
        msg = f"peak {levels.max_db:.1f} dBFS (clipping)"
        out.append(defect("audio_clipping", "medium", "audio", msg))
    if levels.mean_db > HOT_MEAN_DB:
        msg = f"mean loudness {levels.mean_db:.1f} dBFS (too hot)"
        out.append(defect("audio_loudness", "low", "audio", msg))
    return out


class AudioDimension:
    name = "audio"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        levels = ctx.metrics.audio
        defects = [
            *check_speech(ctx.spec, ctx.rubric, ctx.signals, ctx.thr),
            *_level_defects(levels),
        ]
        notes: list[Evidence] = []
        if levels is not None:
            note = f"mean {levels.mean_db:.1f} dBFS, peak {levels.max_db:.1f} dBFS"
            notes.append(Evidence(note=note))
        confidence = (
            0.8 if levels is not None or ctx.signals.voiced_ratio is not None else 0.4
        )
        subs = {"voiced_ratio": ctx.signals.voiced_ratio or 0.0}
        return make_result(
            self.name, score_from_defects(defects), confidence, defects, subs, notes
        )

"""Script adherence (hard gate): dialogue as scripted, beats as scripted, mood roughly matches.

Distinct from action_adherence (which owns per-step defects): this dimension judges the clip
against the SCRIPT — spoken lines (deterministic transcript matching), the summary beat,
entrances/exits and unscripted characters/actions (VLM), and mood/delivery (low weight).
"""

from __future__ import annotations

from ...qa.critic.checks import defect
from ...schema import QADefect
from ..contracts import DimensionResult, EvalInput
from .base import EvalContext, concrete, make_result
from .script_dialogue import dialogue_component

W_DIALOGUE, W_BEATS, W_MOOD = 0.5, 0.4, 0.1
MOOD_FLOOR = 0.5


def _beat_defects(ctx: EvalContext) -> list[QADefect]:
    sv = ctx.rubric.script
    ev = sv.evidence or "script beat review"
    out: list[QADefect] = []
    if not sv.beats_seen:
        out.append(defect("beat_missing", concrete(ev), "script", ev))
    if not sv.entrances_exits_ok:
        out.append(defect("entrance_exit", "medium", "script", ev))
    out += [
        defect("unscripted_character", concrete(ev), name, f"{name} appears; {ev}")
        for name in sv.unscripted_characters
    ]
    out += [
        defect("unscripted_action", "medium", "script", f"{act}; {ev}")
        for act in sv.unscripted_actions
    ]
    return out


def _beat_score(ctx: EvalContext, defects: list[QADefect]) -> float:
    steps = [v.done for v in ctx.rubric.steps]
    done = sum(steps) / len(steps) if steps else 1.0
    penalty = 0.3 * sum(d.severity == "high" for d in defects)
    return max(
        0.0,
        min(done, 1.0) - penalty - 0.1 * sum(d.severity == "medium" for d in defects),
    )


class ScriptAdherence:
    name = "script_adherence"

    def evaluate(self, inp: EvalInput, ctx: EvalContext) -> DimensionResult:
        beat_defects = _beat_defects(ctx)
        beats = _beat_score(ctx, beat_defects)
        mood = max(0.0, min(1.0, ctx.rubric.script.mood_match))
        dlg_defects, dialogue, confidence = dialogue_component(ctx)
        mood_defects: list[QADefect] = []
        if mood < MOOD_FLOOR:
            msg = f"mood/delivery match {mood:.2f}; {ctx.rubric.script.evidence}"
            mood_defects.append(defect("mood_mismatch", "low", "script", msg))
        if dialogue is None:
            score = (W_BEATS * beats + W_MOOD * mood) / (W_BEATS + W_MOOD)
        else:
            score = W_DIALOGUE * dialogue + W_BEATS * beats + W_MOOD * mood
        subs = {"beats": round(beats, 3), "mood": mood}
        if dialogue is not None:
            subs["dialogue"] = round(dialogue, 3)
        match = ctx.metrics.dialogue
        if match is not None and match.lines:
            subs["dialogue_wer"] = round(
                sum(m.wer for m in match.lines) / len(match.lines), 3
            )
        defects = [*dlg_defects, *beat_defects, *mood_defects]
        return make_result(self.name, score, min(confidence, 0.8), defects, subs)

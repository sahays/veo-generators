"""Script adherence (a): spoken dialogue vs scripted lines, from the deterministic transcript."""

from __future__ import annotations

from ...qa.critic.checks import defect
from ...schema import QADefect
from ..metrics.dialogue import MIN_LINE_SIM, DialogueMatch, LineMatch, ScriptedLine
from .base import EvalContext

TEXT_OK_SIM = 0.85
TRANSCRIPT_CONFIDENCE = 0.85
VLM_ONLY_CONFIDENCE = 0.4


def _text_defect(m: LineMatch, at: str, heard: str) -> QADefect | None:
    """>= TEXT_OK_SIM: spoken as scripted; partial: MEDIUM render; below MIN_LINE_SIM: HIGH."""
    if m.similarity >= TEXT_OK_SIM:
        return None
    said = m.line.text[:80]
    msg = f"{at} heard '{heard}' vs scripted '{said}' (sim {m.similarity:.2f})"
    if m.similarity >= MIN_LINE_SIM:
        return defect("line_partial", "medium", m.line.speaker, msg, "render")
    return defect("line_text_mismatch", "high", m.line.speaker, msg)


def _line_defects(m: LineMatch, duration_s: float) -> list[QADefect]:
    """Per-line defects: missing, wrong text, wrong language, wrong speaker, out of order."""
    who, said = m.line.speaker, m.line.text[:80]
    if m.segment is None:
        msg = f"no speech matching '{said}' in t=0.00-{duration_s:.2f}s"
        return [defect("line_missing", "high", who, msg)]
    at = f"t={m.segment.t_start:.2f}s"
    heard = m.segment.text[:80]
    text = _text_defect(m, at, heard)
    out: list[QADefect] = [text] if text else []
    if not m.lang_ok:
        msg = f"{at} '{heard}' not in scripted language '{m.line.lang}'"
        out.append(defect("wrong_language", "high", who, msg))
    if m.speaker_ok is False:
        msg = f"{at} line spoken by {m.segment.speaker}, scripted for {who}"
        out.append(defect("line_wrong_speaker", "high", who, msg))
    if not m.in_order:
        out.append(
            defect("line_order", "medium", who, f"{at} '{said}' out of script order")
        )
    return out


def _dialogue_from_transcript(
    match: DialogueMatch, duration_s: float
) -> tuple[list[QADefect], float]:
    defects = [d for m in match.lines for d in _line_defects(m, duration_s)]
    defects += [
        defect(
            "unscripted_speech",
            "medium",
            s.speaker or "unknown",
            f"t={s.t_start:.2f}s unscripted '{s.text[:80]}'",
        )
        for s in match.extra
    ]
    sims = [m.similarity for m in match.lines]
    base = sum(sims) / len(sims) if sims else 1.0
    return defects, max(0.0, base - 0.15 * len(match.extra))


def _dialogue_from_vlm(ctx: EvalContext, lines: list[ScriptedLine]) -> float:
    """Fallback without a transcript: fraction of scripted speakers seen mouthing."""
    mouth = {v.subject.strip().lower(): v.mouth_moving for v in ctx.rubric.speech}
    speakers = {ln.speaker.lower() for ln in lines}
    return (
        sum(mouth.get(s, False) for s in speakers) / len(speakers) if speakers else 1.0
    )


def dialogue_component(ctx: EvalContext) -> tuple[list[QADefect], float | None, float]:
    """(defects, score or None when there is no dialogue to judge, confidence)."""
    lines = ctx.metrics.lines
    match = ctx.metrics.dialogue
    duration = ctx.metrics.video.duration_s or ctx.spec.duration_s
    if match is not None and (lines or match.extra):
        defects, score = _dialogue_from_transcript(match, duration)
        return defects, score, TRANSCRIPT_CONFIDENCE
    if not lines:
        return [], None, TRANSCRIPT_CONFIDENCE
    return [], _dialogue_from_vlm(ctx, lines), VLM_ONLY_CONFIDENCE

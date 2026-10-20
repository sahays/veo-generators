"""Deterministic dialogue matching: scripted lines vs transcript segments.

`align_lines` is a monotonic weighted alignment (Needleman-Wunsch style DP maximizing total
char-similarity, O(L*S)), so lines are matched in scripted order. Order violations are found
separately from each line's unconstrained best match; unmatched, non-trivial segments are
unscripted (extra) speech.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ...adapters.transcribe import Transcript, TranscriptSegment
from .text import char_similarity, normalize, same_language, word_error_rate

MIN_LINE_SIM = 0.5
MIN_EXTRA_CHARS = 4


@dataclass(frozen=True)
class ScriptedLine:
    speaker: str
    lang: str
    text: str


@dataclass(frozen=True)
class LineMatch:
    """How one scripted line was realised (`segment=None` when it was never heard)."""

    line: ScriptedLine
    segment: TranscriptSegment | None = None
    similarity: float = 0.0
    wer: float = 1.0
    lang_ok: bool = False
    speaker_ok: bool | None = None
    in_order: bool = True


@dataclass(frozen=True)
class DialogueMatch:
    lines: list[LineMatch] = field(default_factory=list)
    extra: list[TranscriptSegment] = field(default_factory=list)
    order_ok: bool = True


def _sim_matrix(
    lines: list[ScriptedLine], segs: list[TranscriptSegment]
) -> list[list[float]]:
    return [[char_similarity(ln.text, s.text) for s in segs] for ln in lines]


def align_lines(sim: list[list[float]]) -> list[int | None]:
    """Monotonic line->segment assignment maximizing total similarity (>= MIN_LINE_SIM)."""
    n, m = len(sim), len(sim[0]) if sim else 0
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            take = sim[i - 1][j - 1] if sim[i - 1][j - 1] >= MIN_LINE_SIM else -1.0
            best[i][j] = max(best[i - 1][j], best[i][j - 1], best[i - 1][j - 1] + take)
    out: list[int | None] = [None] * n
    i, j = n, m
    while i > 0 and j > 0:
        s = sim[i - 1][j - 1]
        if s >= MIN_LINE_SIM and best[i][j] == best[i - 1][j - 1] + s:
            out[i - 1], i, j = j - 1, i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return out


def order_ok(sim: list[list[float]]) -> bool:
    """True when the lines' best-matching segments (ignoring order) appear in script order."""
    picks = [
        max(range(len(row)), key=row.__getitem__)
        for row in sim
        if row and max(row) >= MIN_LINE_SIM
    ]
    return all(a <= b for a, b in itertools.pairwise(picks))


def _is_extra(seg: TranscriptSegment, sims: list[float]) -> bool:
    text = normalize(seg.text).replace(" ", "")
    return len(text) >= MIN_EXTRA_CHARS and (not sims or max(sims) < MIN_LINE_SIM)


def _pick(row: list[float], assigned: int | None) -> tuple[int | None, bool]:
    """Segment for a line: its in-order assignment, else its best out-of-order match."""
    if assigned is not None:
        return assigned, True
    if row and max(row) >= MIN_LINE_SIM:
        return max(range(len(row)), key=row.__getitem__), False
    return None, True


def _line_match(
    line: ScriptedLine, seg: TranscriptSegment | None, sim: float, in_order: bool
) -> LineMatch:
    if seg is None:
        return LineMatch(line=line)
    speaker_ok = (
        None if not seg.speaker else seg.speaker.lower() == line.speaker.lower()
    )
    return LineMatch(
        line=line,
        segment=seg,
        similarity=round(sim, 3),
        wer=round(word_error_rate(line.text, seg.text), 3),
        lang_ok=same_language(line.lang, seg.lang, seg.text),
        speaker_ok=speaker_ok,
        in_order=in_order,
    )


def match_dialogue(lines: list[ScriptedLine], transcript: Transcript) -> DialogueMatch:
    """Align scripted lines to the transcript; report misses, extras and order."""
    segs = transcript.segments
    sim = _sim_matrix(lines, segs)
    assigned = align_lines(sim) if lines and segs else [None] * len(lines)
    picks = [_pick(sim[i] if segs else [], k) for i, k in enumerate(assigned)]
    matches = [
        _line_match(
            ln,
            segs[k] if k is not None else None,
            sim[i][k] if k is not None else 0.0,
            ok,
        )
        for i, (ln, (k, ok)) in enumerate(zip(lines, picks, strict=True))
    ]
    used = {k for k, _ in picks if k is not None}
    columns = [[row[j] for row in sim] for j in range(len(segs))]
    extra = [
        s for j, s in enumerate(segs) if j not in used and _is_extra(s, columns[j])
    ]
    return DialogueMatch(lines=matches, extra=extra, order_ok=order_ok(sim))

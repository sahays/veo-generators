"""Deterministic dialogue matching: scripted lines vs transcript segments.

Transcribers often split one spoken line into several segments ("The cord is freed." /
"Now surrender..."). So each line is aligned against a *window* of consecutive segments
(same or unknown speaker, inter-segment gaps <= MAX_MERGE_GAP_S, at most MAX_WINDOW long).

`align_lines` is a monotonic weighted alignment over segment spans (DP maximizing total
similarity, O(L*S*W)), so lines are matched in scripted order. Order violations are found
separately from each line's unconstrained best window; segments outside every matched window
that resemble no line are unscripted (extra) speech.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from ...adapters.transcribe import Transcript, TranscriptSegment
from .text import char_similarity, normalize, same_language, word_error_rate

MIN_LINE_SIM = 0.5
MIN_EXTRA_CHARS = 4
MAX_MERGE_GAP_S = 1.2
MAX_WINDOW = 4
MIN_FRAGMENT_WORDS = 3

Span = tuple[int, int]  # [start, end) transcript segment indices
_SKIP_SEG, _SKIP_LINE = -1, -2


@dataclass(frozen=True)
class ScriptedLine:
    speaker: str
    lang: str
    text: str


@dataclass(frozen=True)
class LineMatch:
    """How one scripted line was realised (`segment=None` when it was never heard).

    `segment` is the merged window the line aligned to; `span` its segment indices.
    """

    line: ScriptedLine
    segment: TranscriptSegment | None = None
    similarity: float = 0.0
    wer: float = 1.0
    lang_ok: bool = False
    speaker_ok: bool | None = None
    in_order: bool = True
    span: Span | None = None


@dataclass(frozen=True)
class DialogueMatch:
    lines: list[LineMatch] = field(default_factory=list)
    extra: list[TranscriptSegment] = field(default_factory=list)
    order_ok: bool = True


def _speaker(seg: TranscriptSegment) -> str:
    return (seg.speaker or "").strip().casefold()


def merge_spans(segs: list[TranscriptSegment]) -> list[Span]:
    """All mergeable windows: consecutive, gap-bounded, single known speaker, <= MAX_WINDOW."""
    spans: list[Span] = []
    for s, first in enumerate(segs):
        who = _speaker(first)
        spans.append((s, s + 1))
        for e in range(s + 1, min(len(segs), s + MAX_WINDOW)):
            nxt = _speaker(segs[e])
            if segs[e].t_start - segs[e - 1].t_end > MAX_MERGE_GAP_S:
                break
            if who and nxt and nxt != who:
                break
            who = who or nxt
            spans.append((s, e + 1))
    return spans


def merged_segment(segs: list[TranscriptSegment], span: Span) -> TranscriptSegment:
    """One segment covering `span`: joined text, first known speaker/language."""
    part = segs[span[0] : span[1]]
    return TranscriptSegment(
        t_start=part[0].t_start,
        t_end=part[-1].t_end,
        text=" ".join(p.text.strip() for p in part),
        speaker=next((p.speaker for p in part if p.speaker), ""),
        lang=next((p.lang for p in part if p.lang), ""),
    )


def line_similarity(ref: str, hyp: str) -> float:
    """Best of char similarity (spacing-robust) and word similarity (1 - WER, clipped)."""
    return max(char_similarity(ref, hyp), max(0.0, 1.0 - word_error_rate(ref, hyp)))


def _fill(scores: list[list[float]], spans: list[Span], n_segs: int) -> list[list[int]]:
    """DP choice table: best[i][j] = max total score of lines[:i] within segs[:j]."""
    by_end: list[list[int]] = [[] for _ in range(n_segs + 1)]
    for k, (_, end) in enumerate(spans):
        by_end[end].append(k)
    best = [[0.0] * (n_segs + 1) for _ in range(len(scores) + 1)]
    choice = [[_SKIP_LINE] * (n_segs + 1) for _ in range(len(scores) + 1)]
    for i, row in enumerate(scores, start=1):
        for j in range(1, n_segs + 1):
            cell, how = best[i][j - 1], _SKIP_SEG
            if best[i - 1][j] > cell:
                cell, how = best[i - 1][j], _SKIP_LINE
            for k in by_end[j]:
                total = best[i - 1][spans[k][0]] + row[k]
                if row[k] >= MIN_LINE_SIM and total > cell:
                    cell, how = total, k
            best[i][j], choice[i][j] = cell, how
    return choice


def align_lines(
    scores: list[list[float]], spans: list[Span], n_segs: int
) -> list[int | None]:
    """Monotonic line->span assignment (span index per line) maximizing total similarity."""
    choice = _fill(scores, spans, n_segs)
    out: list[int | None] = [None] * len(scores)
    i, j = len(scores), n_segs
    while i > 0 and j > 0:
        how = choice[i][j]
        if how == _SKIP_SEG:
            j -= 1
        elif how == _SKIP_LINE:
            i -= 1
        else:
            out[i - 1], i, j = how, i - 1, spans[how][0]
    return out


def _best(row: list[float]) -> int | None:
    if not row or max(row) < MIN_LINE_SIM:
        return None
    return max(range(len(row)), key=row.__getitem__)


def order_ok(scores: list[list[float]], spans: list[Span]) -> bool:
    """True when the lines' best windows (ignoring order) start in script order."""
    picks = [spans[k][0] for k in map(_best, scores) if k is not None]
    return all(a <= b for a, b in itertools.pairwise(picks))


def _pick(row: list[float], assigned: int | None) -> tuple[int | None, bool]:
    """Window for a line: its in-order assignment, else its best out-of-order match."""
    if assigned is not None:
        return assigned, True
    best = _best(row)
    return best, best is None


def _line_match(
    line: ScriptedLine,
    seg: TranscriptSegment | None,
    sim: float,
    in_order: bool,
    span: Span | None,
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
        span=span,
    )


def _overlaps(a: TranscriptSegment, b: TranscriptSegment) -> bool:
    return a.t_start < b.t_end and b.t_start < a.t_end


def _is_extra(
    seg: TranscriptSegment, best_sim: float, windows: list[TranscriptSegment]
) -> bool:
    """Non-trivial speech resembling no line; short fragments inside a matched window are noise."""
    text = normalize(seg.text)
    if len(text.replace(" ", "")) < MIN_EXTRA_CHARS or best_sim >= MIN_LINE_SIM:
        return False
    fragment = len(text.split()) < MIN_FRAGMENT_WORDS
    return not (fragment and any(_overlaps(seg, w) for w in windows))


def _extras(
    segs: list[TranscriptSegment],
    scores: list[list[float]],
    spans: list[Span],
    used: list[int],
) -> list[TranscriptSegment]:
    covered = {j for k in used for j in range(*spans[k])}
    windows = [merged_segment(segs, spans[k]) for k in used]
    single = {sp[0]: k for k, sp in enumerate(spans) if sp[1] - sp[0] == 1}
    return [
        s
        for j, s in enumerate(segs)
        if j not in covered
        and _is_extra(s, max((row[single[j]] for row in scores), default=0.0), windows)
    ]


def match_dialogue(lines: list[ScriptedLine], transcript: Transcript) -> DialogueMatch:
    """Align scripted lines to merged transcript windows; report misses, extras and order."""
    segs = transcript.segments
    spans = merge_spans(segs)
    windows = [merged_segment(segs, sp) for sp in spans]
    scores = [[line_similarity(ln.text, w.text) for w in windows] for ln in lines]
    assigned = (
        align_lines(scores, spans, len(segs)) if lines and segs else [None] * len(lines)
    )
    picks = [_pick(scores[i], k) for i, k in enumerate(assigned)]
    matches = [
        _line_match(
            ln,
            windows[k] if k is not None else None,
            scores[i][k] if k is not None else 0.0,
            ok,
            spans[k] if k is not None else None,
        )
        for i, (ln, (k, ok)) in enumerate(zip(lines, picks, strict=True))
    ]
    used = [k for k, _ in picks if k is not None]
    extra = _extras(segs, scores, spans, used)
    return DialogueMatch(lines=matches, extra=extra, order_ok=order_ok(scores, spans))

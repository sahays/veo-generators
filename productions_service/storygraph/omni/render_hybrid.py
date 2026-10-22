"""Deterministic `OmniClipSpec` -> Omni prompt text in the V3 hybrid format.

Winner of the controlled prompt-format A/B (`docs/eval/prompt_ab_v1.md`: gate pass 38% vs
12% for JSON, 0 hard cuts, +0.23 action adherence). Layout, in order:

1. One prose paragraph: the literal single-take sentence first, then style, the optional
   `<FIRST_FRAME>` line, then the ordered beats as plain active sentences naming the actor
   (no timecodes, no physics narration, no dialogue).
2. A small labelled block: CHARACTERS (name, `<IMAGE_REF_k>` right after it, brief identity
   always with wardrobe, screen side), OBJECTS ("each exactly one", start/end + holder),
   SETTING, CAMERA (plain cinematography words), DIALOGUE (after beat n, speaker, language,
   voice, verbatim line).
3. Short literal negatives at the end (plus plain-sentence repair levers / retry targets).

Target length is 150-250 words before the adapter's image captions; identity/wardrobe text
is shortened level by level (at clause boundaries, never dropped) to stay within it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .phrasing import (
    Names,
    camera_phrase,
    lang_name,
    object_detail,
    sentence,
    step_text,
    usable,
)
from .relevance import prompt_objects
from .spec import OmniClipSpec, SpeechSpec, SubjectSpec
from .text import clause_cut, strip_null_lead

SINGLE_TAKE: Final[str] = "Single continuous unbroken shot with no scene cuts."
FIRST_FRAME_LINE: Final[str] = (
    "<FIRST_FRAME> The video starts exactly on the provided first frame."
)
OBJECTS_HEADER: Final[str] = (
    "OBJECTS (each exactly one; never duplicated, never disappears):"
)
NEGATIVES: Final[str] = (
    "No other characters. No extra or duplicate props. No text, captions or subtitles."
)
WORD_TARGET: Final[tuple[int, int]] = (150, 250)
CLOTHED_DEFAULT: Final[str] = "fully clothed exactly as in the reference image"
REPAIR_SENTENCES: Final[dict[str, str]] = {  # RepairToken -> plain sentence
    "character_design_matches_refs": "Characters match their reference images exactly.",
    "objects_persist_whole_take": "Every object stays visible for the whole take.",
    "one_action_at_a_time": "One action at a time, in the order written.",
    "screen_positions_locked": "Characters keep their screen positions.",
    "motion_from_first_frame": "Motion starts from the very first frame.",
    "single_consistent_art_style": "One consistent art style throughout.",
}
_DRESSED_KINDS: Final[frozenset[str]] = frozenset({"person", "hybrid"})
_PHYSICS_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:momentum|kinetic|inertia|velocity|trajectory|torque|friction|gravity|"
    r"force|impulse|acceleration|cent(?:er|re) of mass)\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r",\s+")


@dataclass(frozen=True)
class Brevity:
    """Word caps for one character line; the renderer walks down until within budget."""

    identity_words: int
    wardrobe_words: int
    max_goals: int  # retry/repair targets kept in the closing line


BREVITY_LEVELS: Final[tuple[Brevity, ...]] = (
    Brevity(18, 16, 3),
    Brevity(12, 12, 2),
    Brevity(8, 10, 1),
)


def word_count(text: str) -> int:
    return len(text.split())


def render_hybrid(spec: OmniClipSpec) -> str:
    """Hybrid prompt for `spec`, the first brevity level within the word budget."""
    text = ""
    for level in BREVITY_LEVELS:
        text = _render(spec, level)
        if word_count(text) <= WORD_TARGET[1]:
            return text
    return text


def _render(spec: OmniClipSpec, level: Brevity) -> str:
    names = Names.of(spec)
    block = [
        *_characters(spec, names, level),
        *_objects(spec, names),
        _setting(spec, names),
        f"CAMERA: {camera_phrase(spec.camera, names)}",
        *_dialogue(spec, names),
    ]
    return "\n".join([_prose(spec, names), "", *block, _closing(spec, level.max_goals)])


def plain_beat(text: str) -> str:
    """Drop physics-narration clauses ('applying forward momentum'); keep the first clause."""
    head, *rest = _CLAUSE_SPLIT_RE.split(text.rstrip("."))
    return sentence(", ".join([head, *(c for c in rest if not _PHYSICS_RE.search(c))]))


def _prose(spec: OmniClipSpec, names: Names) -> str:
    steps = sorted(spec.sequence or [], key=lambda s: s.n)
    first_frame = bool(spec.continuity and spec.continuity.first_frame)
    parts = [
        SINGLE_TAKE,
        sentence(usable(spec.clip.style)),
        FIRST_FRAME_LINE if first_frame else "",
        *(plain_beat(step_text(s, names)) for s in steps),
    ]
    return " ".join(p for p in parts if p)


def _lower_first(text: str) -> str:
    """'A snug collar' -> 'a snug collar'; acronyms ('LED strip') are kept."""
    return text[:1].lower() + text[1:] if not text[1:2].isupper() else text


def wardrobe_text(subj: SubjectSpec, max_words: int) -> str:
    """Wardrobe words; dressed kinds without wardrobe get an explicit 'fully clothed'."""
    ward = clause_cut(strip_null_lead(subj.wardrobe), max_words)
    if ward:
        return _lower_first(ward)
    return CLOTHED_DEFAULT if subj.kind in _DRESSED_KINDS else ""


def _character_line(subj: SubjectSpec, names: Names, level: Brevity) -> str:
    ident = _lower_first(clause_cut(usable(subj.identity), level.identity_words))
    ward = wardrobe_text(subj, level.wardrobe_words)
    parts = [ident, f"wardrobe: {ward}" if ward else "", f"{subj.screen_pos} of frame"]
    return f"- {names.tagged(subj.id)}: " + "; ".join(p for p in parts if p)


def _characters(spec: OmniClipSpec, names: Names, level: Brevity) -> list[str]:
    subjects = spec.subjects or []
    if not subjects:
        return []
    return ["CHARACTERS:", *(_character_line(s, names, level) for s in subjects)]


def _objects(spec: OmniClipSpec, names: Names) -> list[str]:
    rows = [f"- {object_detail(o, names)}" for o in prompt_objects(spec)]
    return [OBJECTS_HEADER, *rows] if rows else []


def _setting(spec: OmniClipSpec, names: Names) -> str:
    when = (spec.setting.time_of_day or "").strip().lower()
    return f"SETTING: {names.tagged(spec.setting.id)}" + (f", {when}" if when else "")


def speech_slot(after: int | None) -> str:
    """`after beat n` (`before beat 1` for 0, `during the shot` when unanchored)."""
    if after is None:
        return "during the shot"
    return "before beat 1" if after <= 0 else f"after beat {after}"


def _speech_line(line: SpeechSpec, names: Names) -> str:
    who = names.name.get(line.speaker, line.speaker)
    return (
        f"- {speech_slot(line.after)}, {who} ({lang_name(line.lang)}, {line.voice}): "
        f'"{line.text}"'
    )


def _dialogue(spec: OmniClipSpec, names: Names) -> list[str]:
    lines = spec.speech or []
    return ["DIALOGUE:", *(_speech_line(s, names) for s in lines)] if lines else []


def _closing(spec: OmniClipSpec, max_goals: int) -> str:
    levers = [REPAIR_SENTENCES[c] for c in spec.constraints if c in REPAIR_SENTENCES]
    goals = [g.rstrip(".") for g in spec.must_achieve or [] if g.strip()][:max_goals]
    must = f"Make sure: {'; '.join(goals)}." if goals else ""
    return " ".join(p for p in (*levers, must, NEGATIVES) if p)

"""The four prompt variants under test, each a pure function of (compiled spec, first-frame flag).

V1_json    production compact `OmniClipSpec` JSON, unchanged.
V2_prose   expert natural language per the Omni prompt guide: single-shot directive, style,
           setting, tagged characters, counted props, timecoded ordered beats with dialogue in
           the beat it follows, camera, sound design, short literal negatives.
V3_hybrid  short prose paragraph (ordered beats + dialogue) + minimal labelled block
           (characters/objects with tags, holders, camera, dialogue).
V4_minimal one paragraph: actions + dialogue only (tags on first mention, nothing else).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Literal

from ....omni.spec import OmniClipSpec, SubjectSpec
from ..contracts import VariantId
from .phrasing import (
    Names,
    beat_windows,
    camera_phrase,
    fmt_s,
    lang_name,
    object_line,
    sentence,
    speech_text,
    step_text,
    usable,
)

Builder = Callable[[OmniClipSpec, bool], str]
SINGLE_TAKE = "Single continuous unbroken shot with no scene cuts."
NEGATIVES = (
    "No other characters. No extra or duplicate props. No text, captions or subtitles."
)


def _ff_prefix(has_ff: bool) -> str:
    return (
        "<FIRST_FRAME> The video starts exactly on the provided first frame."
        if has_ff
        else ""
    )


SpeechMode = Literal["voiced", "plain", "none"]


def _beats(
    spec: OmniClipSpec, names: Names, timed: bool, speech: SpeechMode
) -> list[str]:
    """One sentence per sequence step; each speech line is appended to the step it follows."""
    lines_of = spec.speech if speech != "none" else None
    voiced = speech == "voiced"
    steps = sorted(spec.sequence or [], key=lambda s: s.n)
    windows = beat_windows(spec.clip.duration_s, len(steps))
    out: list[str] = []
    first = steps[0].n if steps else 0
    for idx, step in enumerate(steps):
        lines = [
            speech_text(sp, names, voiced)
            for sp in lines_of or []
            if max(sp.after if sp.after is not None else -1, first) == step.n
        ]
        text = " ".join([step_text(step, names), *lines])
        if timed:
            lo, hi = windows[idx]
            text = f"[{fmt_s(lo)}-{fmt_s(hi)}] {text}"
        out.append(text)
    known = {s.n for s in steps}
    orphans = [
        speech_text(sp, names, voiced)
        for sp in lines_of or []
        if sp.after is not None and sp.after > first and sp.after not in known
    ]
    return out + orphans


def _subject_sentence(subj: SubjectSpec, names: Names) -> str:
    who = names.tagged(subj.id)
    ident = usable(subj.identity).rstrip(".")
    art = "an" if subj.kind[:1] in "aeiou" else "a"
    desc = f"{who} ({art} {subj.kind}: {ident[0].lower()}{ident[1:]})" if ident else who
    pos = subj.screen_pos
    where = (
        f"in the {pos}"
        if pos in ("center", "background", "foreground")
        else f"on the {pos}"
    )
    text = f"{desc} is {where} of frame"
    if subj.can_speak and not subj.has_mouth:
        text += f"; {subj.name} has no mouth, so the voice comes from its body"
    return sentence(text)


def _setting_sentence(spec: OmniClipSpec, names: Names) -> str:
    st = spec.setting
    when = ", ".join(p for p in (st.time_of_day, st.weather) if p)
    return sentence(f"Setting: {names.tagged(st.id)}" + (f", {when}" if when else ""))


def _sound(spec: OmniClipSpec) -> str:
    sfx = ", ".join(spec.clip.audio.sfx or [])
    music = "Include soft background music." if spec.clip.audio.music else "No music."
    speech = "" if spec.speech else " No dialogue."
    return (f"Sound design: {sfx}. " if sfx else "") + music + speech


def _objects(spec: OmniClipSpec, names: Names) -> list[str]:
    return [object_line(o, names) for o in spec.objects or [] if o.in_frame]


def build_v1(spec: OmniClipSpec, has_ff: bool) -> str:
    """Production prompt: the compiled spec JSON (adapter re-binds tokens identically)."""
    del has_ff
    return spec.render()


def build_v2(spec: OmniClipSpec, has_ff: bool) -> str:
    names = Names.of(spec)
    opening = usable(spec.continuity.opening_state if spec.continuity else None)
    props = _objects(spec, names)
    parts = [
        SINGLE_TAKE,
        sentence(usable(spec.clip.style) or ""),
        _ff_prefix(has_ff),
        _setting_sentence(spec, names),
        *(_subject_sentence(s, names) for s in spec.subjects or []),
        sentence(
            "Props, each appearing exactly once and never vanishing: "
            + "; ".join(props)
        )
        if props
        else "",
        sentence(f"At the start, {opening[0].lower()}{names.resolve(opening)[1:]}")
        if opening
        else "",
        " ".join(_beats(spec, names, timed=True, speech="voiced")),
        camera_phrase(spec, names),
        _sound(spec),
        NEGATIVES,
    ]
    return "\n".join(p for p in parts if p)


def _block(spec: OmniClipSpec, names: Names) -> list[str]:
    rows = ["CHARACTERS:"]
    rows += [
        f"- {names.tagged(s.id)}: {s.screen_pos} of frame" for s in spec.subjects or []
    ]
    rows.append("OBJECTS (each exactly one; never duplicated, never disappears):")
    rows += [f"- {line.removeprefix('exactly one ')}" for line in _objects(spec, names)]
    rows.append(f"SETTING: {names.tagged(spec.setting.id)}")
    rows.append(f"CAMERA: {camera_phrase(spec, names)}")
    if spec.speech:
        rows.append("DIALOGUE:")
        rows += [
            f"- after beat {sp.after}, {names.name.get(sp.speaker, sp.speaker)} "
            f'({lang_name(sp.lang)}, {sp.voice}): "{sp.text}"'
            for sp in spec.speech
        ]
    return rows


def build_v3(spec: OmniClipSpec, has_ff: bool) -> str:
    names = Names.of(spec)
    prose = " ".join(
        p
        for p in (
            SINGLE_TAKE,
            sentence(usable(spec.clip.style) or ""),
            _ff_prefix(has_ff),
            " ".join(_beats(spec, names, timed=False, speech="none")),
        )
        if p
    )
    return "\n".join([prose, "", *_block(spec, names)])


def _tag_first_mentions(text: str, names: Names) -> str:
    for ent_id, tag in names.tag.items():
        name = names.name[ent_id]
        pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
        text = pattern.sub(lambda m, t=tag: f"{m.group(0)} {t}", text, count=1)
    return text


def build_v4(spec: OmniClipSpec, has_ff: bool) -> str:
    names = Names.of(spec)
    body = _tag_first_mentions(
        " ".join(_beats(spec, names, timed=False, speech="plain")), names
    )
    return " ".join(p for p in ("<FIRST_FRAME>" if has_ff else "", body) if p)


BUILDERS: dict[VariantId, Builder] = {
    "V1_json": build_v1,
    "V2_prose": build_v2,
    "V3_hybrid": build_v3,
    "V4_minimal": build_v4,
}

"""Subject (cast) specs and speech entries for the Omni spec.

Only subjects that can speak get speech entries; `lipsync` is true only for speakers with
a mouth. Non-verbal subjects carry their vocalization in `vocal` instead.
"""

from __future__ import annotations

from typing import Final

from ..schema import CastInShot
from ..views import ShotView
from .sequence import speech_anchor
from .spec import SpeechSpec, StepSpec, SubjectSpec
from .symbols import ImageBindings, Symbols
from .text import clause_cut, clean, condense_identity, humanize, strip_null_lead
from .voice import Speaker, build_speaker, language_code

_WARDROBE_LABELS: Final[frozenset[str]] = frozenset({"default", "none", "normal"})
_TRIMMED_WARDROBE_WORDS: Final[int] = 16


def build_speakers(view: ShotView, sym: Symbols) -> dict[str, Speaker]:
    """Traits + voice for every cast member, keyed by entity id."""
    names = {c.entity_id: sym.name(c.entity_id) for c in view.shot.cast}
    out: dict[str, Speaker] = {}
    for eid, nm in names.items():
        app = view.cast_appearances.get(eid)
        others = [n for k, n in names.items() if k != eid]
        out[eid] = build_speaker(
            view.cast_entities.get(eid),
            nm,
            app.visual_description if app else "",
            others,
        )
    return out


def _wardrobe(raw: str, full: bool) -> str:
    """Wardrobe text ('default' is a state label, not wardrobe); first clauses when trimmed.

    A leading null label ('None; unclad chassis ...') is dropped and trimming always ends
    on a clause boundary, so identity never ships a half phrase (prompt A/B v1, §5).
    """
    text = strip_null_lead(humanize(raw))
    if text.lower() in _WARDROBE_LABELS:
        return ""
    return text if full else clause_cut(text, _TRIMMED_WARDROBE_WORDS)


def _subject(
    view: ShotView, c: CastInShot, spk: Speaker, sym: Symbols, n_sent: int, full: bool
) -> SubjectSpec:
    app = view.cast_appearances.get(c.entity_id)
    st = view.cast_states.get(c.entity_id, {})
    others = [n for k, n in sym.names.items() if k != c.entity_id]
    r = sym.resolver
    wardrobe = clean((app.wardrobe if app else None) or st.get("wearing"), r)
    desc = app.visual_description if app else ""
    ident = condense_identity(desc, r, others, max(1, n_sent))
    traits = spk.traits
    return SubjectSpec(
        id=sym.ids[c.entity_id],
        name=spk.name,
        kind=traits.kind.value,
        identity=ident or None,
        wardrobe=_wardrobe(wardrobe, full) or None,
        holding=sym.ids.get(st.get("holding", "")),
        screen_pos=c.position,
        framing=c.framing,
        can_speak=traits.can_speak,
        has_mouth=traits.has_mouth,
        vocal=None if traits.can_speak else traits.vocalization,
    )


def build_subjects(
    view: ShotView,
    spk: dict[str, Speaker],
    sym: Symbols,
    bindings: ImageBindings,
    with_ref: int,
    without_ref: int,
    full_wardrobe: bool = True,
) -> list[SubjectSpec]:
    """One subject per unique cast member; identity never drops below one sentence."""
    out: list[SubjectSpec] = []
    for c in {c.entity_id: c for c in view.shot.cast}.values():
        ref = bindings.ref_by_entity.get(c.entity_id)
        n_sent = with_ref if ref else without_ref
        subj = _subject(view, c, spk[c.entity_id], sym, n_sent, full_wardrobe)
        out.append(subj.model_copy(update={"ref_image": ref}))
    return out


def _speech_slot(anchor: int | None, sequence: list[StepSpec]) -> int | None:
    """Anchor speech before the final step (never after the last action)."""
    if anchor is None or not sequence:
        return anchor
    return min(anchor, len(sequence) - 1)


def build_speech(
    view: ShotView,
    spk: dict[str, Speaker],
    sym: Symbols,
    prompt: str,
    sequence: list[StepSpec],
) -> list[SpeechSpec]:
    """Spoken lines in scene order, only for cast members that can speak."""
    lines = sorted(view.dialogue_lines, key=lambda d: d.order_in_scene)
    out: list[SpeechSpec] = []
    for d in lines:
        s = spk.get(d.speaker_id)
        if s is None or not s.traits.can_speak or not d.text.strip():
            continue
        delivery = clean(d.delivery, sym.resolver)
        out.append(
            SpeechSpec(
                after=_speech_slot(speech_anchor(prompt, sequence, d.text), sequence),
                speaker=sym.ids[d.speaker_id],
                lang=language_code(d.language),
                text=d.text.strip(),
                delivery=delivery if delivery and delivery != "natural" else None,
                voice=s.profile,
                lipsync=s.traits.has_mouth,
            )
        )
    return out

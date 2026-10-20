"""Subject (cast) specs and speech entries for the Omni spec.

Only subjects that can speak get speech entries; `lipsync` is true only for speakers with
a mouth. Non-verbal subjects carry their vocalization in `vocal` instead.
"""

from __future__ import annotations

from ..schema import CastInShot
from ..views import ShotView
from .sequence import speech_anchor
from .spec import SpeechSpec, StepSpec, SubjectSpec
from .symbols import ImageBindings, Symbols
from .text import clean, condense_identity, humanize
from .voice import Speaker, build_speaker, language_code


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


def _subject(
    view: ShotView, c: CastInShot, spk: Speaker, sym: Symbols, n_sent: int
) -> SubjectSpec:
    app = view.cast_appearances.get(c.entity_id)
    st = view.cast_states.get(c.entity_id, {})
    others = [n for k, n in sym.names.items() if k != c.entity_id]
    r = sym.resolver
    wardrobe = clean((app.wardrobe if app else None) or st.get("wearing"), r)
    ident = condense_identity(app.visual_description if app else "", r, others, n_sent)
    traits = spk.traits
    return SubjectSpec(
        id=sym.ids[c.entity_id],
        name=spk.name,
        kind=traits.kind.value,
        identity=ident or None,
        wardrobe=humanize(wardrobe) or None,
        holding=sym.ref(clean(st.get("holding"), r)),
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
) -> list[SubjectSpec]:
    """One subject per unique cast member; referenced subjects get shorter identity text."""
    out: list[SubjectSpec] = []
    for c in {c.entity_id: c for c in view.shot.cast}.values():
        ref = bindings.ref_by_entity.get(c.entity_id)
        subj = _subject(
            view, c, spk[c.entity_id], sym, with_ref if ref else without_ref
        )
        out.append(subj.model_copy(update={"ref_image": ref}))
    return out


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
                after=speech_anchor(prompt, sequence, d.text),
                speaker=sym.ids[d.speaker_id],
                lang=language_code(d.language),
                text=d.text.strip(),
                delivery=delivery if delivery and delivery != "natural" else None,
                voice=s.profile,
                lipsync=s.traits.has_mouth,
            )
        )
    return out

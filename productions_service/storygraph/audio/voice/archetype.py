"""Deterministic archetype classification of a speaking character (robot/child/adult, gender)."""

from __future__ import annotations

import re
from typing import Final, Literal

from ...clips.species import ActorKind
from ...omni.voice import build_speaker
from ...schema import Entity
from ...schemas.voice import VoiceArchetype

Gender = Literal["female", "male", ""]
_SENTENCE_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+|\n+")
_FEMALE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:she|her|hers|herself)\b", re.IGNORECASE
)
_MALE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:he|him|his|himself)\b", re.IGNORECASE
)
_MIN_PRONOUN_MARGIN: Final[int] = 2


def _names_re(names: list[str]) -> re.Pattern[str] | None:
    alts = [re.escape(n) for n in names if n.strip()]
    return re.compile(rf"\b(?:{'|'.join(alts)})\b", re.IGNORECASE) if alts else None


def own_context(source: str, names: list[str], other_names: list[str]) -> str:
    """Sentences naming only this character, plus pronoun follow-ups naming nobody.

    O(sentences): one pass, carrying "last sentence was about this character".
    """
    mine, others = _names_re(names), _names_re(other_names)
    if mine is None:
        return ""
    picked: list[str] = []
    carry = False
    for sent in (s.strip() for s in _SENTENCE_RE.split(source or "")):
        has_other = bool(others and others.search(sent))
        has_me = bool(mine.search(sent))
        about_me = has_me and not has_other
        follow_up = carry and not has_me and not has_other
        if about_me or follow_up:
            picked.append(sent)
        carry = about_me or follow_up
    return " ".join(picked)


def pronoun_gender(text: str) -> Gender:
    """Majority pronoun gender with a minimum margin; "" when ambiguous."""
    fem, masc = len(_FEMALE_RE.findall(text)), len(_MALE_RE.findall(text))
    if fem - masc >= _MIN_PRONOUN_MARGIN or fem and not masc:
        return "female"
    if masc - fem >= _MIN_PRONOUN_MARGIN or masc and not fem:
        return "male"
    return ""


def _from_profile(profile: str, gender: Gender) -> VoiceArchetype | None:
    """Map the Omni voice-profile phrase (omni/voice.py) to an archetype."""
    low = profile.casefold()
    if "girl" in low:
        return "child_female"
    if "child" in low:
        return "child_female" if gender == "female" else "child_male"
    elder = "elderly" in low
    if "female" in low:
        return "elder_female" if elder else "adult_female"
    if "male" in low:
        return "elder_male" if elder else "adult_male"
    return None


def classify_archetype(
    entity: Entity, source: str, other_names: list[str]
) -> VoiceArchetype:
    """Robot/creature by kind; persons by age words, then pronouns; else neutral."""
    names = [entity.canonical_name, *entity.aliases]
    context = own_context(source, names, other_names)
    speaker = build_speaker(entity, entity.canonical_name, context, other_names)
    if speaker.traits.kind == ActorKind.ROBOT:
        return "robot"
    if speaker.traits.kind in (ActorKind.ANIMAL, ActorKind.HYBRID):
        return "creature"
    gender = pronoun_gender(context)
    by_profile = _from_profile(speaker.profile, gender)
    if by_profile is not None:
        return by_profile
    if gender == "female":
        return "adult_female"
    return "adult_male" if gender == "male" else "neutral"

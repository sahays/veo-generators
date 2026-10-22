"""Voice profiles and language codes for Omni speech entries (only actors allowed to speak)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ..clips.species import (
    ActorKind,
    ActorTraits,
    attribute_values,
    entity_traits,
    own_sentences,
)
from ..schema import Entity

LANG_CODES: Final[dict[str, str]] = {
    "hi": "hi-IN",
    "hindi": "hi-IN",
    "ta": "ta-IN",
    "tamil": "ta-IN",
    "te": "te-IN",
    "telugu": "te-IN",
    "bn": "bn-IN",
    "bengali": "bn-IN",
    "mr": "mr-IN",
    "marathi": "mr-IN",
    "english": "en",
}


def _re(words: str) -> re.Pattern[str]:
    return re.compile(rf"\b(?:{words})\b", re.IGNORECASE)


# (pattern, profile) checked in order against the actor's OWN identity text.
_PERSON_VOICES: Final[tuple[tuple[re.Pattern[str], str], ...]] = (
    (_re("girl|daughter|sister|princess"), "young girl's voice, bright and clear"),
    (
        _re("boy|son|kid|child|toddler|baby"),
        "young child's voice, bright and higher-pitched",
    ),
    (
        _re("grandmother|grandma|old woman|elderly woman"),
        "warm elderly female voice, gentle and slow",
    ),
    (
        _re("woman|mother|mom|lady|female|queen"),
        "warm clear adult female voice",
    ),
    (_re("grandfather|grandpa|old man|elderly man|sage"), "deep elderly male voice"),
    (_re("man|father|dad|male|king|warrior"), "steady adult male voice"),
)
_DEFAULT_VOICE: Final[str] = "warm clear natural voice"
_ROBOT_VOICE: Final[str] = "bright synthetic robotic voice with a light metallic timbre"


@dataclass(frozen=True)
class Speaker:
    """Typed contract for one cast member's voice."""

    name: str
    traits: ActorTraits
    profile: str


def voice_profile(
    traits: ActorTraits, identity_text: str, attrs: dict[str, str]
) -> str:
    """Deterministic, shot-invariant voice profile from the actor's own traits and identity."""
    if attrs.get("voice_profile", "").strip():
        return attrs["voice_profile"].strip()
    if traits.kind == ActorKind.ROBOT:
        return _ROBOT_VOICE
    if traits.kind in (ActorKind.ANIMAL, ActorKind.HYBRID):
        if not traits.can_speak:
            return f"non-verbal {traits.species or 'animal'} {traits.vocalization}"
        return f"expressive {traits.species or 'creature'} voice"
    return next(
        (v for p, v in _PERSON_VOICES if p.search(identity_text)), _DEFAULT_VOICE
    )


def build_speaker(
    entity: Entity | None, name: str, description: str, others: list[str]
) -> Speaker:
    """Resolve traits + voice for a cast member from its own attributes and description."""
    traits = entity_traits(entity, description, others)
    attrs = attribute_values(entity)
    identity = " ".join([name, *attrs.values(), *own_sentences(description, others)])
    return Speaker(name, traits, voice_profile(traits, identity, attrs))


def language_code(raw: str | None) -> str:
    """Normalise a language tag to BCP-47 ('hindi' -> 'hi-IN', 'en-US' kept)."""
    code = (raw or "en").strip()
    return LANG_CODES.get(code.lower(), code)

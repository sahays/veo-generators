"""Deterministic actor-kind detection (robot / animal / hybrid / person) from an entity's OWN text.

Whole-word regexes only (so "delicate" never matches "cat"), applied first to an explicit
kind attribute (`species`, `kind`, `creature_type`, `race`), then to the entity's name,
aliases, attributes and the sentences of its own description that do not mention other
characters. HYBRID covers mythic / anthropomorphic beings (vanara, centaur, mermaid,
humanoid or clothed animals…): they speak and may also vocalize like their animal side;
a hybrid term wins over person words in the same text ("vanara prince" is a vanara).
Attribute overrides: `can_speak`, `has_mouth` ("true"/"false").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..schema import Appearance, Entity, EntityType


class ActorKind(StrEnum):
    ROBOT = "robot"
    ANIMAL = "animal"
    HYBRID = "hybrid"
    PERSON = "person"


def _words_re(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


_ROBOT_RE: Final[re.Pattern[str]] = _words_re(
    (
        "robots?",
        "robotic",
        "androids?",
        "droids?",
        "automatons?",
        "cyborgs?",
        "mecha",
        "mechanical",
        "clockwork",
    )
)
# species word -> non-verbal vocalization family
_ANIMAL_SOUNDS: Final[dict[str, str]] = {
    "dog": "barks, yips and whimpers",
    "puppy": "barks, yips and whimpers",
    "puppies": "barks, yips and whimpers",
    "retriever": "barks, yips and whimpers",
    "hound": "barks and howls",
    "cat": "meows and purrs",
    "kitten": "meows and purrs",
    "bird": "chirps and squawks",
    "parrot": "squawks and chirps",
    "vulture": "screeches and wing flaps",
    "eagle": "screeches",
    "owl": "hoots",
    "horse": "neighs and snorts",
    "cow": "moos",
    "monkey": "chatters and squeaks",
    "elephant": "trumpets",
    "tiger": "growls and roars",
    "lion": "growls and roars",
    "bear": "growls",
    "rabbit": "soft squeaks and sniffs",
    "mouse": "squeaks",
    "fox": "yips",
    "wolf": "howls and growls",
    "duck": "quacks",
    "animal": "animal sounds",
}
_ANIMAL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(" + "|".join(sorted(_ANIMAL_SOUNDS, key=len, reverse=True)) + r")s?\b",
    re.IGNORECASE,
)
_SPEAKING_CREATURE_RE: Final[re.Pattern[str]] = _words_re(
    (
        "talking",
        "speaking",
        "sentient",
        "divine",
        "demi-?gods?",
        "gods?",
        "goddess",
        "deity",
        "mythical",
        "mythic",
        "anthropomorphic",
    )
)
_HYBRID_RE: Final[re.Pattern[str]] = _words_re(
    (
        "vanaras?", "centaurs?", "merm(?:aid|an|en|aids)", "minotaurs?", "satyrs?",
        "fauns?", "werewol(?:f|ves)", "nagas?", "naginis?", "garudas?", "kinnaras?",
        "yakshas?", "rakshas(?:a|as|i)", "asuras?", "gandharvas?", "humanoids?",
        "anthropomorphic", "beast-?folk", "harp(?:y|ies)", "sphinx(?:es)?", "elf",
        "elves", "dwarf", "dwarves", "goblins?", "ogres?", "trolls?", "fair(?:y|ies)",
        "sprites?", "pix(?:ie|ies)", "nymphs?", "dryads?",
    )
)  # fmt: skip
# Cues that an animal is anthropomorphic (clothed, upright, hands): it becomes HYBRID.
_ANTHRO_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:dhoti|robes?|tunic|armou?r|armlets?|vestments|cloak|waistcoat|"
    r"walks? upright|bipedal|on two legs)\b",
    re.IGNORECASE,
)
_KIND_KEYS: Final[tuple[str, ...]] = (
    "species",
    "kind",
    "creature_type",
    "race",
    "being",
)
_PERSON_RE: Final[re.Pattern[str]] = _words_re(
    (
        "boys?",
        "girls?",
        "man",
        "men",
        "woman",
        "women",
        "child",
        "children",
        "kids?",
        "human",
        "person",
        "lady",
        "gentleman",
        "mother",
        "father",
        "grand(?:mother|father|ma|pa)",
        "king",
        "queen",
        "prince",
        "princess",
        "sage",
        "warrior",
        "toddler",
        "baby",
        "teen(?:ager)?",
        "son",
        "daughter",
        "brother",
        "sister",
        "monk",
        "farmer",
    )
)
_MOUTHLESS_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:visor|mouthless|faceplate|speaker grille|no mouth|without (?:a )?mouth|"
    r"screen face|(?:led|lcd|digital|display|screen)[- ](?:face|eyes|display|screen))\b",
    re.IGNORECASE,
)
_MOUTH_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:mouth|lips?|smil(?:e|es|ing)|grin(?:s|ning)?|teeth|tongue|muzzle|snout|beak|jaw)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+")
_FALSY: Final[frozenset[str]] = frozenset({"false", "no", "0", "none", "never"})
_TRUTHY: Final[frozenset[str]] = frozenset({"true", "yes", "1"})


@dataclass(frozen=True)
class ActorTraits:
    """Typed contract: what an actor is and how it may vocalize."""

    kind: ActorKind
    species: str = ""
    can_speak: bool = True
    has_mouth: bool = False

    @property
    def vocalization(self) -> str:
        return _ANIMAL_SOUNDS.get(self.species, "non-verbal sounds")


def attribute_values(entity: Entity | None) -> dict[str, str]:
    """Flatten `Entity.attributes` (AttributeVal) to plain `key -> value` strings."""
    if entity is None:
        return {}
    return {k: v.value for k, v in entity.attributes.items() if v.value}


def own_sentences(description: str, other_names: list[str]) -> list[str]:
    """Return description sentences that do not mention any other character by name."""
    pats = [_words_re((re.escape(n),)) for n in other_names if n.strip()]
    return [
        s.strip()
        for s in _SENTENCE_SPLIT_RE.split(description or "")
        if s.strip() and not any(p.search(s) for p in pats)
    ]


def _override(attrs: dict[str, str], key: str, default: bool) -> bool:
    raw = attrs.get(key, "").strip().lower()
    if raw in _FALSY:
        return False
    return True if raw in _TRUTHY else default


def _classify(text: str) -> tuple[ActorKind, str] | None:
    """Return (kind, species) for one evidence tier: hybrid terms win, else earliest kind."""
    hybrid = _HYBRID_RE.search(text)
    if hybrid:
        return ActorKind.HYBRID, hybrid.group(0).lower()
    hits: list[tuple[int, ActorKind, str]] = []
    for kind, pattern in ((ActorKind.ROBOT, _ROBOT_RE), (ActorKind.PERSON, _PERSON_RE)):
        m = pattern.search(text)
        if m:
            hits.append((m.start(), kind, ""))
    animal = _ANIMAL_RE.search(text)
    if animal:
        hits.append((animal.start(), ActorKind.ANIMAL, animal.group(1).lower()))
    if not hits:
        return None
    _, kind, species = min(hits, key=lambda h: h[0])
    return kind, species


def has_mouth_evidence(text: str, kind: ActorKind = ActorKind.ROBOT) -> bool:
    """Mouth/lips must be explicitly described (people have one unless described otherwise);
    visor, screen or LED faces never count."""
    if _MOUTHLESS_RE.search(text):
        return False
    humanlike = kind in (ActorKind.PERSON, ActorKind.HYBRID)
    return humanlike or bool(_MOUTH_RE.search(text))


def _anthropomorphize(
    found: tuple[ActorKind, str], text: str, attrs: dict[str, str]
) -> tuple[ActorKind, str]:
    """An animal described as clothed / upright / anthropomorphic is a HYBRID being."""
    kind, species = found
    clothed = bool(attrs.get("attire", "").strip()) or bool(_ANTHRO_RE.search(text))
    return (
        (ActorKind.HYBRID, species) if kind == ActorKind.ANIMAL and clothed else found
    )


def detect_traits(tiers: list[str], attrs: dict[str, str]) -> ActorTraits:
    """Classify from evidence tiers in priority order (first decisive tier wins; default person).

    An explicit kind attribute (`species`, `kind`, …) is the first tier.
    """
    text = " ".join([*tiers, *attrs.values()])
    explicit = " ".join(attrs.get(k, "") for k in _KIND_KEYS)
    found = next(
        (c for t in (explicit, *tiers) if t.strip() and (c := _classify(t))), None
    )
    kind, species = (
        _anthropomorphize(found, text, attrs) if found else (ActorKind.PERSON, "")
    )
    mouth = _override(attrs, "has_mouth", has_mouth_evidence(text, kind))
    talks = kind != ActorKind.ANIMAL or bool(_SPEAKING_CREATURE_RE.search(text))
    return ActorTraits(kind, species, _override(attrs, "can_speak", talks), mouth)


def entity_traits(
    entity: Entity | None, description: str, other_names: list[str]
) -> ActorTraits:
    """Traits from name+aliases+attributes, then the first own sentence, then the rest."""
    attrs = attribute_values(entity)
    names = [entity.canonical_name, *entity.aliases] if entity else []
    own = own_sentences(description, other_names)
    head = " ".join([*names, *attrs.values()])
    return detect_traits([head, own[0] if own else "", " ".join(own[1:])], attrs)


def actor_traits(
    entities: list[Entity], appearances: list[Appearance]
) -> dict[str, ActorTraits]:
    """Traits for every CHARACTER entity (latest appearance description), in O(E + A)."""
    chars = [e for e in entities if e.entity_type == EntityType.CHARACTER]
    names = [e.canonical_name for e in chars]
    desc_by_entity = {a.entity_id: a.visual_description for a in appearances}
    return {
        e.id: entity_traits(
            e,
            desc_by_entity.get(e.id, ""),
            [n for n in names if n != e.canonical_name],
        )
        for e in chars
    }

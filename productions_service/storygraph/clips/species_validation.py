"""Screenplay rule: actions and vocalizations must match the actor's species.

Only animals (and hybrid/anthropomorphic beings) bark/meow/neigh…; non-speaking actors
(animals unless the story makes them talk) carry no dialogue lines or speech verbs. Noun
uses ("the tree's rough bark") and speech idioms ("barks an order", "roars with laughter")
are not vocalizations (`verb_use`). Codes are `S2_*`: a violation is rewritten by the
Screenwriter for that scene with the message as feedback, and is never a permanent block
(S6 demotes it to a shot warning when remediation runs out).
"""

from __future__ import annotations

import re
from typing import Final

from ..schema import DialogueLine, Scene
from .species import ActorKind, ActorTraits
from .validation import ClipIssue
from .verb_use import is_vocalization

CODE_SPECIES_ACTION: Final[str] = "S2_CLIP_SPECIES_ACTION"
CODE_MUTE_SPEAKER: Final[str] = "S2_CLIP_MUTE_SPEAKER"
SPECIES_CODES: Final[frozenset[str]] = frozenset(
    {CODE_SPECIES_ACTION, CODE_MUTE_SPEAKER}
)
_MAY_VOCALIZE: Final[frozenset[ActorKind]] = frozenset(
    {ActorKind.ANIMAL, ActorKind.HYBRID}
)

_ANIMAL_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:bark(?:s|ed|ing)?|woof(?:s|ed|ing)?|meow(?:s|ed|ing)?|miaow(?:s|ed)?|"
    r"purr(?:s|ed|ing)?|neigh(?:s|ed|ing)?|whinn(?:y|ies|ied)|moo(?:s|ed|ing)?|"
    r"oink(?:s|ed)?|quack(?:s|ed|ing)?|bleat(?:s|ed|ing)?|cluck(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)
_SPEECH_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:says|said|speaks|spoke|tells|told|replies|replied|asks|asked|whispers|exclaims)\b",
    re.IGNORECASE,
)
_SENTENCE_RE: Final[re.Pattern[str]] = re.compile(r"[^.!?]+[.!?]?")


class _Names:
    """Case-insensitive matcher over actor names (with their ids)."""

    def __init__(self, traits: dict[str, ActorTraits], names: dict[str, str]) -> None:
        self.ids = {
            n.lower(): eid for eid, n in names.items() if eid in traits and n.strip()
        }
        alt = "|".join(re.escape(n) for n in sorted(self.ids, key=len, reverse=True))
        self.pattern = re.compile(rf"\b(?:{alt})\b", re.IGNORECASE) if alt else None
        self.words = frozenset(w for n in self.ids for w in n.split())

    def nearest(self, sentence: str, upto: int) -> str | None:
        """Entity id of the last character named before offset `upto`."""
        if self.pattern is None:
            return None
        hits = list(self.pattern.finditer(sentence, 0, upto))
        return self.ids.get(hits[-1].group(0).lower()) if hits else None


def _verb_subjects(
    text: str,
    verb_re: re.Pattern[str],
    default_actor: str,
    names: _Names,
    literal: bool,
) -> list[tuple[str, str]]:
    """`(subject_id, verb)` per verb match; subject = nearest preceding named actor.

    With `literal`, noun uses and speech idioms are skipped.
    """
    found: list[tuple[str, str]] = []
    for sent in _SENTENCE_RE.findall(text):
        for verb in verb_re.finditer(sent):
            if literal and not is_vocalization(
                sent, verb.start(), verb.end(), names.words
            ):
                continue
            subject = names.nearest(sent, verb.start())
            found.append((subject or default_actor, verb.group(0)))
    return found


def _vocal_issues(
    scene_id: str,
    label: str,
    text: str,
    default_actor: str,
    ctx: tuple[dict[str, ActorTraits], dict[str, str], _Names],
) -> list[ClipIssue]:
    traits, names, matcher = ctx
    issues: list[ClipIssue] = []
    for subj, verb in _verb_subjects(
        text, _ANIMAL_ONLY_RE, default_actor, matcher, True
    ):
        tr = traits.get(subj)
        if tr is not None and tr.kind not in _MAY_VOCALIZE:
            msg = (
                f"{label}: {names.get(subj, subj)} ({tr.kind}) cannot '{verb}' literally — "
                f"only animals do; rewrite as speech or an action fitting a {tr.kind}."
            )
            issues.append(ClipIssue(CODE_SPECIES_ACTION, scene_id, msg))
    return issues


def _step_issues(
    scene: Scene, ctx: tuple[dict[str, ActorTraits], dict[str, str], _Names]
) -> list[ClipIssue]:
    traits, names, matcher = ctx
    issues: list[ClipIssue] = []
    for st in scene.interaction_steps:
        if st.actor_id not in traits:
            continue
        text = st.action or st.description
        label = f"Step {st.step_index}"
        issues.extend(_vocal_issues(scene.id, label, text, st.actor_id, ctx))
        for subj, _verb in _verb_subjects(
            text, _SPEECH_RE, st.actor_id, matcher, False
        ):
            tr = traits.get(subj)
            if tr is not None and not tr.can_speak:
                msg = f"{label}: {names.get(subj, subj)} is non-verbal ({tr.vocalization} only)."
                issues.append(ClipIssue(CODE_MUTE_SPEAKER, scene.id, msg))
    return issues


def validate_species_rules(
    scene: Scene,
    dialogues: list[DialogueLine],
    traits: dict[str, ActorTraits],
    names: dict[str, str],
) -> list[ClipIssue]:
    """Run species/vocalization rules over one scene's steps, clip prompts and dialogue."""
    ctx = (traits, names, _Names(traits, names))
    issues = _step_issues(scene, ctx)
    for clip in scene.clips:
        label = f"Clip {clip.clip_index}"
        issues.extend(_vocal_issues(scene.id, label, clip.omni_prompt, "", ctx))
    for dl in dialogues:
        tr = traits.get(dl.speaker_id)
        if tr is not None and not tr.can_speak:
            who = names.get(dl.speaker_id, dl.speaker_id)
            msg = f"Dialogue '{dl.id}' is spoken by non-verbal {who}; use {tr.vocalization} in the action instead."
            issues.append(ClipIssue(CODE_MUTE_SPEAKER, scene.id, msg))
    return issues

"""Screenplay rule: actions and vocalizations must match the actor's species.

Only animals bark/meow/neigh…; non-speaking actors (animals unless the story makes them
talk) carry no dialogue lines or speech verbs. Codes are `S2_*` so a violation routes the
scene back to the Screenwriter.
"""

from __future__ import annotations

import re
from typing import Final

from ..schema import DialogueLine, Scene
from .species import ActorKind, ActorTraits
from .validation import ClipIssue

CODE_SPECIES_ACTION: Final[str] = "S2_CLIP_SPECIES_ACTION"
CODE_MUTE_SPEAKER: Final[str] = "S2_CLIP_MUTE_SPEAKER"

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


def _nearest_actor(
    sentence: str, upto: int, name_re: re.Pattern[str], ids: dict[str, str]
) -> str | None:
    """Return the entity id of the last character named before offset `upto` in `sentence`."""
    hits = [m for m in name_re.finditer(sentence, 0, upto)]
    return ids.get(hits[-1].group(0).lower()) if hits else None


def _prompt_issues(
    scene_id: str,
    label: str,
    prompt: str,
    traits: dict[str, ActorTraits],
    names: dict[str, str],
) -> list[ClipIssue]:
    """Flag animal-only vocal verbs whose nearest preceding subject is not an animal."""
    ids = {n.lower(): eid for eid, n in names.items() if eid in traits and n.strip()}
    if not ids:
        return []
    alt = "|".join(re.escape(n) for n in sorted(ids, key=len, reverse=True))
    name_re = re.compile(rf"\b(?:{alt})\b", re.IGNORECASE)
    issues: list[ClipIssue] = []
    for sent in _SENTENCE_RE.findall(prompt):
        for verb in _ANIMAL_ONLY_RE.finditer(sent):
            actor = _nearest_actor(sent, verb.start(), name_re, ids)
            if actor and traits[actor].kind != ActorKind.ANIMAL:
                msg = f"{label}: {names[actor]} ({traits[actor].kind}) cannot '{verb.group(0)}' — only animals do."
                issues.append(ClipIssue(CODE_SPECIES_ACTION, scene_id, msg))
    return issues


def _step_issues(
    scene: Scene, traits: dict[str, ActorTraits], names: dict[str, str]
) -> list[ClipIssue]:
    issues: list[ClipIssue] = []
    for st in scene.interaction_steps:
        tr = traits.get(st.actor_id)
        if tr is None:
            continue
        who = names.get(st.actor_id, "actor")
        text = st.action or st.description
        verb = _ANIMAL_ONLY_RE.search(text)
        if verb and tr.kind != ActorKind.ANIMAL:
            msg = f"Step {st.step_index}: {who} ({tr.kind}) cannot '{verb.group(0)}' — only animals do."
            issues.append(ClipIssue(CODE_SPECIES_ACTION, scene.id, msg))
        if not tr.can_speak and _SPEECH_RE.search(text):
            msg = f"Step {st.step_index}: {who} is non-verbal ({tr.vocalization} only)."
            issues.append(ClipIssue(CODE_MUTE_SPEAKER, scene.id, msg))
    return issues


def validate_species_rules(
    scene: Scene,
    dialogues: list[DialogueLine],
    traits: dict[str, ActorTraits],
    names: dict[str, str],
) -> list[ClipIssue]:
    """Run species/vocalization rules over one scene's steps, clip prompts and dialogue."""
    issues = _step_issues(scene, traits, names)
    for clip in scene.clips:
        label = f"Clip {clip.clip_index}"
        issues.extend(_prompt_issues(scene.id, label, clip.omni_prompt, traits, names))
    for dl in dialogues:
        tr = traits.get(dl.speaker_id)
        if tr is not None and not tr.can_speak:
            who = names.get(dl.speaker_id, dl.speaker_id)
            msg = f"Dialogue '{dl.id}' is spoken by non-verbal {who}; use {tr.vocalization} in the action instead."
            issues.append(ClipIssue(CODE_MUTE_SPEAKER, scene.id, msg))
    return issues

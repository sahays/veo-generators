"""Ordered `sequence` steps for one clip, plus speech anchoring (`after` step number).

Steps follow `ClipScript.step_indices` order exactly; order is the only temporal signal
(no timestamps, no per-step seconds).
"""

from __future__ import annotations

import re
from typing import Final

from ..clips.models import ClipScript
from ..schema import InteractionStep
from ..views import ShotView
from .spec import StepSpec
from .symbols import Symbols
from .text import clean

_DEFAULT_VERB: Final[str] = "acts"
_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[\w'-]+")


def clip_steps(view: ShotView, clip: ClipScript) -> list[InteractionStep]:
    """The clip's interaction steps in the clip's own authored order (O(n))."""
    by_index = {s.step_index: s for s in view.scene.interaction_steps}
    ordered = dict.fromkeys(clip.step_indices)
    return [by_index[i] for i in ordered if i in by_index]


def _verb_detail(step: InteractionStep, sym: Symbols) -> tuple[str, str]:
    """(verb, detail): explicit verb first, else the action text; detail never repeats verb."""
    r = sym.resolver
    bare = next(
        (
            v.strip()
            for v in (step.action_verb, step.verb)
            if v.strip() not in ("", _DEFAULT_VERB)
        ),
        "",
    )
    action = clean(step.action or step.description, r)
    verb = clean(bare, r) or action or _DEFAULT_VERB
    candidates = (
        clean(step.detail, r),
        clean(step.contact_mechanics, r),
        action if action != verb else "",
    )
    return verb, next((c for c in candidates if c and c != verb), "")


def build_sequence(steps: list[InteractionStep], sym: Symbols) -> list[StepSpec]:
    """Numbered machine steps with symbolic actor/target ids."""
    out: list[StepSpec] = []
    for n, step in enumerate(steps, 1):
        verb, detail = _verb_detail(step, sym)
        out.append(
            StepSpec(
                n=n,
                actor=sym.ref(step.actor_id) or "unknown",
                verb=verb,
                target=sym.ref(step.target_id),
                detail=detail or None,
                end_state=clean(step.post_state, sym.resolver) or None,
            )
        )
    return out


def speech_anchor(prompt: str, sequence: list[StepSpec], text: str) -> int | None:
    """Number of steps whose verb precedes the quoted line in the clip prompt (None if unquoted)."""
    pos = prompt.find(text.strip()) if text.strip() else -1
    if pos < 0:
        return None
    cursor, done = 0, 0
    for step in sequence:
        words = _WORD_RE.findall(step.verb)
        hit = (
            re.search(rf"\b{re.escape(words[0])}", prompt[cursor:], re.IGNORECASE)
            if words
            else None
        )
        if hit is None or cursor + hit.start() >= pos:
            break
        cursor += hit.end()
        done += 1
    return done

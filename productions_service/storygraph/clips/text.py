"""Deterministic text helpers for Omni clip prompts (timestamp stripping, prose composition)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .limits import count_spoken_words

# Matches "(0.0–3.5s)", "0-3s", "3.5 – 7.0 s", "t=0.0s", "at 2.5s", "[t=4s]".
TIMESTAMP_RANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"\(?\[?\s*\d+(?:\.\d+)?\s*s?\s*[–—-]\s*\d+(?:\.\d+)?\s*s(?:ec(?:onds?)?)?\b\s*\]?\)?",
    re.IGNORECASE,
)
_POINT_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"\(?\[?\s*(?:\bt\s*=\s*|\bat\s+)\d+(?:\.\d+)?\s*s(?:ec(?:onds?)?)?\b\s*\]?\)?",
    re.IGNORECASE,
)
_SPACES_RE: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
_ORDINALS: Final[tuple[str, str, str]] = ("First", "Then", "Finally")


@dataclass(frozen=True)
class DialogueRef:
    """Typed contract for a persisted dialogue line referenced by a clip."""

    line_id: str
    speaker_name: str
    text: str

    @property
    def word_count(self) -> int:
        return count_spoken_words(self.text)


@dataclass(frozen=True)
class StepRef:
    """Typed contract for an interaction step consumed by the clip builder."""

    step_index: int
    actor_name: str
    action: str
    pre_state: str
    post_state: str
    key_action: bool = False  # travels or handles an object (counts toward CLIP_LIMITS)


def has_timestamps(text: str) -> bool:
    """Return True when `text` contains a time range or point timestamp Omni cannot follow."""
    return bool(TIMESTAMP_RANGE_RE.search(text) or _POINT_TIMESTAMP_RE.search(text))


def strip_timestamps(text: str) -> str:
    """Remove time ranges / point timestamps and collapse whitespace."""
    cleaned = _POINT_TIMESTAMP_RE.sub(" ", TIMESTAMP_RANGE_RE.sub(" ", text))
    cleaned = cleaned.replace(" ,", ",").replace(" .", ".")
    return _SPACES_RE.sub(" ", cleaned).strip()


def _sentence(text: str) -> str:
    body = text.strip().rstrip(".")
    return f"{body}." if body else ""


def _ordinal(pos: int, total: int) -> str:
    if total == 1:
        return ""
    if pos == 0:
        return _ORDINALS[0]
    return _ORDINALS[2] if pos == total - 1 else _ORDINALS[1]


def _action_clause(step: StepRef) -> str:
    action = step.action.strip()
    if step.actor_name and step.actor_name.lower() not in action.lower():
        return f"{step.actor_name} {action[:1].lower()}{action[1:]}"
    return action


def compose_action_prose(steps: list[StepRef]) -> str:
    """Join steps as one continuous present-tense moment: 'First …, then …, finally …'."""
    parts: list[str] = []
    for pos, step in enumerate(steps):
        lead = _ordinal(pos, len(steps))
        clause = _action_clause(step)
        parts.append(_sentence(f"{lead}, {clause}" if lead else clause))
    return " ".join(p for p in parts if p)


def dialogue_sentence(line: DialogueRef) -> str:
    """Render a dialogue line verbatim with its speaker name for Omni lip-sync."""
    return f'{line.speaker_name} says: "{line.text.strip()}"'


def compose_omni_prompt(steps: list[StepRef], lines: list[DialogueRef]) -> str:
    """Compose a self-contained, timestamp-free clip paragraph from steps and dialogue."""
    prose = compose_action_prose(steps)
    spoken = " ".join(dialogue_sentence(ln) for ln in lines)
    return strip_timestamps(f"{prose} {spoken}".strip())


def ensure_dialogue_verbatim(prompt: str, lines: list[DialogueRef]) -> str:
    """Append any dialogue line whose exact text is absent from `prompt`."""
    missing = [ln for ln in lines if ln.text.strip() and ln.text.strip() not in prompt]
    if not missing:
        return prompt
    extra = " ".join(dialogue_sentence(ln) for ln in missing)
    return f"{prompt.rstrip()} {extra}".strip()

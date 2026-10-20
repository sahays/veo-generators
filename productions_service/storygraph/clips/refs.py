"""Adapters from StoryGraph schema nodes to the typed clip-builder contracts."""

from __future__ import annotations

from ..schema import DialogueLine, Entity, InteractionStep
from .text import DialogueRef, StepRef


def step_refs(steps: list[InteractionStep], names: dict[str, str]) -> list[StepRef]:
    """Map interaction steps to `StepRef`, resolving actor IDs to display names."""
    return [
        StepRef(
            step_index=s.step_index,
            actor_name=names.get(s.actor_id, ""),
            action=s.action or s.description,
            pre_state=s.pre_state,
            post_state=s.post_state,
        )
        for s in steps
    ]


def dialogue_refs(
    lines: list[DialogueLine], names: dict[str, str]
) -> list[DialogueRef]:
    """Map persisted dialogue lines (spoken order) to `DialogueRef` with speaker names."""
    ordered = sorted(lines, key=lambda d: d.order_in_scene)
    return [
        DialogueRef(
            line_id=d.id,
            speaker_name=names.get(d.speaker_id, d.speaker_id),
            text=d.text,
        )
        for d in ordered
    ]


def entity_names(entities: list[Entity]) -> dict[str, str]:
    return {e.id: e.canonical_name for e in entities}

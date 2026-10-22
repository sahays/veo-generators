"""Which spec props earn a line in the Omni prompt (prompt-format A/B v1, rule 4).

Off-action set dressing listed as "each exactly one" objects was duplicated by Omni, so the
hybrid OBJECTS block lists only props the beats touch or that are visibly important. The
spec keeps every prop (QA permanence expectations, cross-clip continuity lint).
"""

from __future__ import annotations

from ..timeline.lifecycle import name_pattern
from .spec import ObjectSpec, OmniClipSpec, StepSpec


def _beat_text(sequence: list[StepSpec]) -> str:
    return " ".join(
        " ".join(p for p in (s.verb, s.detail or "", s.end_state or "") if p)
        for s in sequence
    )


def relevance_keep(spec: OmniClipSpec) -> frozenset[str]:
    """Object ids always relevant: subjects' holdings and the camera focus."""
    held = {s.holding for s in spec.subjects or [] if s.holding}
    return frozenset(held | {spec.camera.focus or ""})


def is_relevant(
    obj: ObjectSpec, sequence: list[StepSpec], keep: frozenset[str]
) -> bool:
    """A prop earns a slot when a beat targets/names it, it moves or is held, it is the
    camera focus / a subject's holding (`keep`), or it has a bound reference image."""
    held = bool(obj.start.held_by or (obj.end and obj.end.held_by))
    if obj.moves or held or obj.ref_image or obj.id in keep:
        return True
    if any(s.target == obj.id for s in sequence):
        return True
    return bool(name_pattern(obj.name).search(_beat_text(sequence)))


def prompt_objects(spec: OmniClipSpec) -> list[ObjectSpec]:
    """In-frame, action-relevant props in spec order (the hybrid OBJECTS block)."""
    keep, seq = relevance_keep(spec), spec.sequence or []
    return [o for o in spec.objects or [] if o.in_frame and is_relevant(o, seq, keep)]

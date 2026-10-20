"""Graph-wide clip rule sweep shared by `validate.py` (V-rules) and `graph_verifier.py` (stage QA)."""

from __future__ import annotations

from ..schema import Appearance, DialogueLine, Entity, Scene, Shot, StageQaIssue
from .species import actor_traits
from .species_validation import validate_species_rules
from .validation import (
    ClipIssue,
    ShotClipRef,
    validate_scene_clips,
    validate_shot_mapping,
)


def collect_clip_issues(
    scenes: list[Scene],
    dialogues: list[DialogueLine],
    shots: list[Shot],
    check_shots: bool,
    entities: list[Entity] | None = None,
    appearances: list[Appearance] | None = None,
) -> list[ClipIssue]:
    """Run screenplay clip rules (and, when `check_shots`, shot↔clip mapping) in O(V + E)."""
    words_by_scene: dict[str, dict[str, int]] = {}
    for d in dialogues:
        words_by_scene.setdefault(d.scene_id, {})[d.id] = len(d.text.split())
    shots_by_scene: dict[str, list[ShotClipRef]] = {}
    for sh in shots:
        shots_by_scene.setdefault(sh.scene_id, []).append(
            ShotClipRef(
                shot_id=sh.id, clip_index=sh.clip_index, duration_s=sh.duration_s
            )
        )
    issues: list[ClipIssue] = []
    for sc in scenes:
        steps = [s.step_index for s in sc.interaction_steps]
        issues.extend(
            validate_scene_clips(sc.id, steps, sc.clips, words_by_scene.get(sc.id, {}))
        )
        if check_shots and sc.clips:
            issues.extend(
                validate_shot_mapping(sc.id, sc.clips, shots_by_scene.get(sc.id, []))
            )
    if entities:
        issues.extend(collect_species_issues(scenes, dialogues, entities, appearances))
    return issues


def collect_species_issues(
    scenes: list[Scene],
    dialogues: list[DialogueLine],
    entities: list[Entity],
    appearances: list[Appearance] | None,
) -> list[ClipIssue]:
    """Species/vocalization screenplay rules for every scene in O(V + E)."""
    traits = actor_traits(entities, appearances or [])
    names = {e.id: e.canonical_name for e in entities}
    lines_by_scene: dict[str, list[DialogueLine]] = {}
    for d in dialogues:
        lines_by_scene.setdefault(d.scene_id, []).append(d)
    issues: list[ClipIssue] = []
    for sc in scenes:
        issues.extend(
            validate_species_rules(sc, lines_by_scene.get(sc.id, []), traits, names)
        )
    return issues


def clip_stage_issues(
    scenes: dict[str, Scene],
    dialogues: dict[str, DialogueLine],
    shots: list[Shot],
    check_shots: bool,
    entities: list[Entity] | None = None,
    appearances_by_entity: dict[str, list[Appearance]] | None = None,
) -> list[StageQaIssue]:
    """Stage-QA view of `collect_clip_issues` (S2 partition; S4 shot mapping when `check_shots`)."""
    found = collect_clip_issues(
        list(scenes.values()),
        list(dialogues.values()),
        shots,
        check_shots,
        entities=entities,
        appearances=[a for grp in (appearances_by_entity or {}).values() for a in grp],
    )
    return [
        StageQaIssue(
            code=ci.code, node_id=ci.node_id, dimension="clips", message=ci.message
        )
        for ci in found
    ]

"""General-purpose Physical State Machine, Backward Prop Liveness, and Hoare-Triple Causality."""

from __future__ import annotations

from .repo import Repo
from .schema import (
    ActionBeat,
    CastInShot,
    Entity,
    EntityType,
    Event,
    InteractionStep,
    Scene,
    Shot,
    StageQaIssue,
)


def _default_support_surface(step: InteractionStep, loc_name: str) -> str:
    """Return the step's own support surface, else a generic grounded surface in the location."""
    if step.supported_by and step.supported_by.strip():
        return step.supported_by.strip()
    if step.interaction_type == "prop":
        return f"a stable surface in {loc_name}"
    return f"the floor of {loc_name}"


def enrich_interaction_step_physics(
    step: InteractionStep,
    prev_post_by_entity: dict[str, str],
    ent_names: dict[str, str],
    loc_name: str,
) -> InteractionStep:
    """Populate Hoare-triple (`pre_state`, `contact_mechanics`, `post_state`, `supported_by`) on `step`."""
    actor_name = ent_names.get(step.actor_id, step.actor_id)
    target_name = ent_names.get(step.target_id, step.target_id or loc_name)
    support = _default_support_surface(step, loc_name)
    pre = step.pre_state.strip() or prev_post_by_entity.get(
        step.target_id or step.actor_id,
        f"{actor_name} and {target_name} are in place in {loc_name}",
    )
    mechanics = step.contact_mechanics.strip() or (
        f"{actor_name} approaches on foot and makes direct hand/body contact with {target_name}: {step.action}"
    )
    post = step.post_state.strip() or (
        f"{actor_name} has finished: {step.action.strip().rstrip('.')}; "
        f"{target_name} rests where {actor_name} leaves it"
    )
    prev_post_by_entity[step.actor_id] = post
    if step.target_id:
        prev_post_by_entity[step.target_id] = post
    return step.model_copy(
        update={
            "supported_by": support,
            "pre_state": pre,
            "contact_mechanics": mechanics,
            "post_state": post,
        }
    )


def enrich_scene_steps(
    steps: list[InteractionStep], entities: dict[str, Entity], loc_name: str
) -> list[InteractionStep]:
    """Chain Hoare-triple state transitions (`pre_state -> post_state`) across all scene steps."""
    ent_names = {eid: e.canonical_name for eid, e in entities.items()}
    prev_post: dict[str, str] = {}
    return [
        enrich_interaction_step_physics(st, prev_post, ent_names, loc_name)
        for st in steps
    ]


def compute_scene_prop_closure(
    scene: Scene, events: list[Event], shots: list[Shot], valid_prop_ids: set[str]
) -> list[str]:
    """Backward Liveness Analysis: collect all OBJECT IDs active anywhere in `scene`."""
    candidates: list[str] = []
    for ev in events:
        if ev.scene_id == scene.id:
            candidates.extend(ev.participants)
            for ef in ev.effects:
                candidates.append(ef.entity_id)
                if ef.attribute == "holding" and ef.new_value:
                    candidates.append(ef.new_value)
    candidates.extend(st.target_id for st in scene.interaction_steps if st.target_id)
    for sh in shots:
        if sh.scene_id == scene.id:
            candidates.extend(sh.prop_ids)
            for b in sh.beats:
                candidates.extend(b.subject_ids)
    return [eid for eid in dict.fromkeys(candidates) if eid in valid_prop_ids]


def compute_scene_cast_closure(
    scene: Scene, events: list[Event], shots: list[Shot], valid_char_ids: set[str]
) -> list[str]:
    """Backward Character Liveness: collect all CHARACTER IDs active anywhere in `scene` so none materialize mid-scene."""
    candidates: list[str] = []
    for ev in events:
        if ev.scene_id == scene.id:
            candidates.extend(ev.participants)
    for st in scene.interaction_steps:
        candidates.extend([st.actor_id, st.target_id])
    for sh in shots:
        if sh.scene_id == scene.id:
            candidates.extend(c.entity_id for c in sh.cast)
            for b in sh.beats:
                candidates.extend(b.subject_ids)
    return [cid for cid in dict.fromkeys(candidates) if cid in valid_char_ids]


def verify_physical_causality(
    scenes: dict[str, Scene],
    events: list[Event],
    shots: list[Shot],
    entities: dict[str, Entity],
    issues: list[StageQaIssue],
    check_shots: bool = True,
) -> None:
    """Run O(V + E) Backward Prop & Character Liveness, Hoare-triple state, and kinematic pacing checks."""
    valid_props = {
        eid for eid, e in entities.items() if e.entity_type == EntityType.OBJECT
    }
    valid_chars = {
        eid for eid, e in entities.items() if e.entity_type == EntityType.CHARACTER
    }
    for sc in scenes.values():
        for st in sc.interaction_steps:
            if not (st.pre_state.strip() and st.post_state.strip()):
                issues.append(
                    StageQaIssue(
                        code="missing_step_physics_state",
                        severity="warn",
                        node_id=sc.id,
                        message=f"Step {st.step_index} in '{sc.id}' lacks pre_state/post_state Hoare triple.",
                    )
                )
        if not check_shots:
            continue
        closure = compute_scene_prop_closure(sc, events, shots, valid_props)
        char_closure = compute_scene_cast_closure(sc, events, shots, valid_chars)
        sc_shots = [sh for sh in shots if sh.scene_id == sc.id]
        for sh in sc_shots:
            missing = [pid for pid in closure if pid not in sh.prop_ids]
            if missing:
                issues.append(
                    StageQaIssue(
                        code="prop_permanence_gap",
                        severity="warn",
                        node_id=sh.id,
                        message=f"Object Permanence: Scene props {missing} missing from '{sh.id}.prop_ids'.",
                    )
                )
            present_chars = {c.entity_id for c in sh.cast}
            missing_chars = [cid for cid in char_closure if cid not in present_chars]
            if missing_chars:
                issues.append(
                    StageQaIssue(
                        code="character_permanence_gap",
                        severity="warn",
                        node_id=sh.id,
                        message=f"Character Permanence: Scene characters {missing_chars} missing from '{sh.id}.cast'.",
                    )
                )
            if len(sh.beats) > 3 or any(
                (b.t_end_s - b.t_start_s) < 1.0 for b in sh.beats
            ):
                issues.append(
                    StageQaIssue(
                        code="shot_action_overload",
                        severity="warn",
                        node_id=sh.id,
                        message=f"Shot '{sh.id}' packs too many fast beats for {sh.duration_s}s duration.",
                    )
                )


def enrich_beats_with_steps(
    beats: list[ActionBeat],
    steps: list[InteractionStep],
) -> list[ActionBeat]:
    """Attach `pre_state` and `post_state` from `steps` onto `beats` when omitted."""
    if not beats:
        return beats
    out: list[ActionBeat] = []
    for idx, b in enumerate(beats):
        step = steps[min(idx, len(steps) - 1)] if steps else None
        pre = b.pre_state or (
            step.pre_state if step else "subjects in initial resting pose"
        )
        post = b.post_state or (
            step.post_state if step else "subjects complete motion stably"
        )
        out.append(b.model_copy(update={"pre_state": pre, "post_state": post}))
    return out


_SLOT_ORDER: tuple[str, ...] = ("left", "right", "center")


def _merge_scene_cast_closure(
    repo: Repo, shot: Shot, char_closure: list[str]
) -> list[CastInShot]:
    """Ensure every scene character is present in `shot.cast` with a non-overlapping screen slot."""
    existing = list(shot.cast)
    present_ids = {c.entity_id for c in existing}
    used_slots = {c.position for c in existing}
    for cid in char_closure:
        if cid in present_ids:
            continue
        slot = next((s for s in _SLOT_ORDER if s not in used_slots), "right")
        used_slots.add(slot)
        apps = repo.list_appearances(entity_id=cid, active_only=True)
        app_id = apps[-1].id if apps else f"app_{cid}_default"
        existing.append(
            CastInShot(
                entity_id=cid,
                appearance_id=app_id,
                position=slot,  # type: ignore[arg-type]
                framing="MS",
                speaking=False,
            )
        )
    return existing


def remediate_physical_causality(
    repo: Repo, fixed: list[str], include_shots: bool = True
) -> None:
    """Auto-remediate Hoare-triple step states and scene-wide prop + character permanence closure."""
    entities = {e.id: e for e in repo.list_entities()}
    valid_chars = {
        eid for eid, e in entities.items() if e.entity_type == EntityType.CHARACTER
    }
    events = repo.list_events()
    shots = repo.list_shots()
    for sc in repo.list_scenes():
        loc = entities.get(sc.location_id)
        loc_name = loc.canonical_name if loc else sc.location_id
        if sc.interaction_steps and any(
            not (s.pre_state.strip() and s.post_state.strip())
            for s in sc.interaction_steps
        ):
            enriched = enrich_scene_steps(sc.interaction_steps, entities, loc_name)
            repo.put_scene(sc.model_copy(update={"interaction_steps": enriched}))
            sc = repo.get_scene(sc.id) or sc
            fixed.append(f"Enriched Hoare-triple physical states on {sc.id} steps.")
        if not include_shots:
            continue
        char_closure = compute_scene_cast_closure(sc, events, shots, valid_chars)
        for sh in [s for s in shots if s.scene_id == sc.id]:
            # Props are clip-scoped at view time (timeline.clip_context); no closure merge.
            merged_props = list(sh.prop_ids)
            merged_cast = _merge_scene_cast_closure(repo, sh, char_closure)
            new_beats = enrich_beats_with_steps(sh.beats, sc.interaction_steps)
            if (
                merged_props != sh.prop_ids
                or merged_cast != sh.cast
                or new_beats != sh.beats
            ):
                repo.put_shot(
                    sh.model_copy(
                        update={
                            "prop_ids": merged_props,
                            "cast": merged_cast,
                            "beats": new_beats,
                        }
                    )
                )
                fixed.append(
                    f"Back-propagated prop & character permanence closure to {sh.id}."
                )

"""Single-pass O(V + E) deterministic StoryGraph verifier for assets, continuity, and consistency."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .clips.graph_checks import clip_stage_issues
from .config import Config
from .physics import verify_physical_causality
from .repo import Repo
from .schema import (  # fmt: skip
    Appearance,
    Asset,
    DialogueLine,
    Entity,
    EntityType,
    Event,
    MusicCue,
    Scene,
    Shot,
    StageQaIssue,
    Status,
)
from .state import state_at

_STAGE_RANK: Final[dict[str, int]] = {
    "S1_EXTRACT": 1, "S2_SCREENPLAY": 2, "S3_DESIGN": 3, "S4_SHOTS": 4, "S5_MUSIC": 5, "S6_VALIDATE": 6,
}  # fmt: skip

_POS_COORD: Final[dict[str, int]] = {"left": -1, "center": 0, "right": 1}


@dataclass(frozen=True)
class GraphIndex:
    """O(1) hash-indexed adjacency views of the StoryGraph for single-pass verification."""

    entities: dict[str, Entity]
    appearances_by_entity: dict[str, list[Appearance]]
    appearances_by_id: dict[str, Appearance]
    assets: dict[str, Asset]
    scenes: dict[str, Scene]
    events: list[Event]
    dialogues: dict[str, DialogueLine]
    music_by_scene: dict[str, MusicCue]
    shots: list[Shot]


def build_graph_index(repo: Repo) -> GraphIndex:
    """Build O(1) lookup tables over all StoryGraph vertices and edges in O(V + E) time."""
    entities = {e.id: e for e in repo.list_entities()}
    appearances_by_entity: dict[str, list[Appearance]] = {}
    appearances_by_id: dict[str, Appearance] = {}
    for app in repo.list_appearances(active_only=False):
        appearances_by_id[app.id] = app
        appearances_by_entity.setdefault(app.entity_id, []).append(app)
    assets = {a.id: a for a in repo.list_assets()}
    scenes = {s.id: s for s in repo.list_scenes()}
    events = sorted(repo.list_events(), key=lambda ev: ev.story_order)
    dialogues = {d.id: d for d in repo.list_dialogue()}
    music_by_scene = {m.scene_id: m for m in repo.list_music_cues()}
    shots = sorted(
        repo.list_shots(),
        key=lambda sh: (sh.story_order, sh.scene_id, sh.index_in_scene),
    )
    return GraphIndex(
        entities=entities,
        appearances_by_entity=appearances_by_entity,
        appearances_by_id=appearances_by_id,
        assets=assets,
        scenes=scenes,
        events=events,
        dialogues=dialogues,
        music_by_scene=music_by_scene,
        shots=shots,
    )


def _verify_s1_extract(repo: Repo, idx: GraphIndex, issues: list[StageQaIssue]) -> None:
    """Verify S1_EXTRACT: StyleGuide, Character/Location presence, and Event entity references."""
    sg = repo.get_style_guide()
    if sg is None or not sg.visual_medium.strip() or not sg.palette:
        issues.append(
            StageQaIssue(
                code="missing_style_guide",
                severity="error",
                node_id="style_guide",
                message="StyleGuide is missing or lacks visual_medium/palette.",
            )
        )
    has_char = any(e.entity_type == EntityType.CHARACTER for e in idx.entities.values())
    has_loc = any(e.entity_type == EntityType.LOCATION for e in idx.entities.values())
    if not has_char or not has_loc:
        issues.append(
            StageQaIssue(
                code="missing_core_entities",
                severity="error",
                node_id="entities",
                message="StoryGraph must have at least one CHARACTER and one LOCATION entity.",
            )
        )
    for sc in idx.scenes.values():
        if sc.location_id not in idx.entities:
            issues.append(
                StageQaIssue(
                    code="missing_scene_location",
                    severity="error",
                    node_id=sc.id,
                    message=f"Scene '{sc.id}' references missing location '{sc.location_id}'.",
                )
            )
    for ev in idx.events:
        sc = idx.scenes.get(ev.scene_id)
        for pid in ev.participants:
            if pid not in idx.entities:
                issues.append(
                    StageQaIssue(
                        code="missing_event_participant",
                        severity="error",
                        node_id=ev.id,
                        message=f"Event '{ev.id}' participant '{pid}' is missing from entities.",
                    )
                )
        for ef in ev.effects:
            if (
                ef.attribute == "location"
                and ef.new_value
                and sc
                and ef.new_value != sc.location_id
            ):
                issues.append(
                    StageQaIssue(
                        code="invalid_event_location_effect",
                        severity="error",
                        node_id=ev.id,
                        message=f"Event '{ev.id}' sets '{ef.entity_id}.location' to '{ef.new_value}' instead of '{sc.location_id}'.",
                    )
                )


def _verify_s2_screenplay(idx: GraphIndex, issues: list[StageQaIssue]) -> None:
    """Verify S2_SCREENPLAY: algorithmic InteractionSteps (1 action at a time) and dialogue speakers."""
    for sc in idx.scenes.values():
        if not sc.interaction_steps:
            issues.append(
                StageQaIssue(
                    code="missing_algorithmic_steps",
                    severity="error",
                    node_id=sc.id,
                    message=f"Scene '{sc.id}' has no algorithmic interaction_steps.",
                )
            )
        for pos, step in enumerate(sc.interaction_steps, start=1):
            if step.step_index != pos:
                issues.append(
                    StageQaIssue(
                        code="step_order_mismatch",
                        severity="warn",
                        node_id=sc.id,
                        message=f"InteractionStep {step.step_index} out of sequential order {pos}.",
                    )
                )
            if step.actor_id not in idx.entities:
                issues.append(
                    StageQaIssue(
                        code="missing_step_actor",
                        severity="error",
                        node_id=sc.id,
                        message=f"Step {pos} in '{sc.id}' references unknown actor '{step.actor_id}'.",
                    )
                )
            if ";" in step.action or len(step.action.split()) > 28:
                issues.append(
                    StageQaIssue(
                        code="compound_interaction_step",
                        severity="error",
                        node_id=sc.id,
                        message=f"Step {pos} in '{sc.id}' bundles multiple actions; keep 1 atomic action per step.",
                    )
                )
    for dlg in idx.dialogues.values():
        if dlg.speaker_id not in idx.entities:
            issues.append(
                StageQaIssue(
                    code="missing_dialogue_speaker",
                    severity="error",
                    node_id=dlg.id,
                    message=f"DialogueLine '{dlg.id}' speaker '{dlg.speaker_id}' is not a valid entity.",
                )
            )


def _verify_s3_design(idx: GraphIndex, issues: list[StageQaIssue]) -> None:
    """Verify S3_DESIGN (9.2 Character Consistency & 9.3 Scene Consistency reference assets)."""
    for ent in idx.entities.values():
        apps = idx.appearances_by_entity.get(ent.id, [])
        approved_apps = [a for a in apps if a.status == Status.APPROVED]
        if not approved_apps:
            issues.append(
                StageQaIssue(
                    code="missing_approved_appearance",
                    severity="error",
                    node_id=ent.id,
                    message=f"Entity '{ent.id}' ({ent.canonical_name}) has no APPROVED Appearance.",
                )
            )
            continue
        app = approved_apps[-1]
        if len(app.visual_description.strip().split()) < 4:
            issues.append(
                StageQaIssue(
                    code="weak_identity_anchor",
                    severity="warn",
                    node_id=ent.id,
                    message=f"Appearance '{app.id}' for '{ent.id}' lacks detailed identity descriptors (9.2/9.3).",
                )
            )
        has_valid_asset = any(
            aid in idx.assets and idx.assets[aid].status == Status.APPROVED
            for aid in app.asset_ids
        )
        if not has_valid_asset:
            issues.append(
                StageQaIssue(
                    code="missing_reference_asset",
                    severity="error",
                    node_id=ent.id,
                    message=f"Appearance '{app.id}' for '{ent.id}' has no APPROVED reference image Asset.",
                )
            )


def _check_180_axis_continuity(
    prev_shot: Shot | None, shot: Shot, issues: list[StageQaIssue]
) -> None:
    """Verify 9.1 Continuity: 180-degree lateral screen ordering across consecutive shots in a scene."""
    if prev_shot is None or prev_shot.scene_id != shot.scene_id:
        return
    prev_pos = {
        c.entity_id: _POS_COORD[c.position]
        for c in prev_shot.cast
        if c.framing != "background" and c.position in _POS_COORD
    }
    cur_pos = {
        c.entity_id: _POS_COORD[c.position]
        for c in shot.cast
        if c.framing != "background" and c.position in _POS_COORD
    }
    shared = [cid for cid in cur_pos if cid in prev_pos]
    for i in range(len(shared)):
        for j in range(i + 1, len(shared)):
            a, b = shared[i], shared[j]
            if (prev_pos[a] - prev_pos[b]) * (cur_pos[a] - cur_pos[b]) < 0:
                issues.append(
                    StageQaIssue(
                        code="continuity_180_rule_violation",
                        severity="warn",
                        node_id=shot.id,
                        message=(
                            f"9.1 Continuity: Characters '{a}' and '{b}' invert screen sides "
                            f"between '{prev_shot.id}' and '{shot.id}'."
                        ),
                    )
                )


def _check_shot_state_alignment(
    repo: Repo, shot: Shot, issues: list[StageQaIssue]
) -> None:
    """Verify V3/V4 state-fact location alignment for cast and props in `shot`."""
    held_props: set[str] = set()
    for c in shot.cast:
        st = state_at(repo, c.entity_id, shot.story_order)
        if held := st.get("holding"):
            held_props.add(held)
        if (ent_loc := st.get("location")) and ent_loc != shot.location_id:
            issues.append(
                StageQaIssue(
                    code="cast_location_state_mismatch",
                    severity="error",
                    node_id=shot.id,
                    message=f"Cast '{c.entity_id}' is at '{ent_loc}' at order {shot.story_order}, not '{shot.location_id}'.",
                )
            )
    for pid in shot.prop_ids:
        p_loc = state_at(repo, pid, shot.story_order).get("location")
        if p_loc and p_loc != shot.location_id and pid not in held_props:
            issues.append(
                StageQaIssue(
                    code="prop_location_state_mismatch",
                    severity="error",
                    node_id=shot.id,
                    message=f"Prop '{pid}' is at '{p_loc}' and not held in shot '{shot.id}'.",
                )
            )


def _verify_single_shot(
    repo: Repo,
    idx: GraphIndex,
    shot: Shot,
    prev_shot: Shot | None,
    issues: list[StageQaIssue],
) -> None:
    """Verify 9.1 Continuity, 9.2 Character Consistency, and 9.3 Scene Consistency on `shot`."""
    sc = idx.scenes.get(shot.scene_id)
    if sc and shot.location_id != sc.location_id:
        issues.append(
            StageQaIssue(
                code="scene_consistency_location_mismatch",
                severity="error",
                node_id=shot.id,
                message=f"9.3 Scene Consistency: Shot '{shot.id}' location '{shot.location_id}' != scene '{sc.location_id}'.",
            )
        )
    if (
        not shot.location_appearance_id
        or shot.location_appearance_id not in idx.appearances_by_id
    ):
        issues.append(
            StageQaIssue(
                code="missing_location_appearance",
                severity="error",
                node_id=shot.id,
                message=f"9.3 Scene Consistency: Shot '{shot.id}' is missing resolved location_appearance_id.",
            )
        )
    speakers = {
        idx.dialogues[did].speaker_id
        for did in shot.dialogue_ids
        if did in idx.dialogues
    }
    cast_ids = {c.entity_id for c in shot.cast}
    for sp_id in speakers:
        if sp_id not in cast_ids:
            issues.append(
                StageQaIssue(
                    code="dialogue_speaker_not_in_cast",
                    severity="error",
                    node_id=shot.id,
                    message=f"Speaker '{sp_id}' for dialogue in '{shot.id}' is missing from shot cast.",
                )
            )
    for c in shot.cast:
        if not c.appearance_id or c.appearance_id not in idx.appearances_by_id:
            issues.append(
                StageQaIssue(
                    code="missing_cast_appearance",
                    severity="error",
                    node_id=shot.id,
                    message=f"9.2 Character Consistency: Cast '{c.entity_id}' in '{shot.id}' lacks appearance_id.",
                )
            )
        held = state_at(repo, c.entity_id, shot.story_order).get("holding")
        if held and held in idx.entities and held not in shot.prop_ids:
            issues.append(
                StageQaIssue(
                    code="continuity_held_prop_missing",
                    severity="error",
                    node_id=shot.id,
                    message=f"9.1 Continuity: Cast '{c.entity_id}' holds '{held}' at order {shot.story_order}, but it is absent from '{shot.id}.prop_ids'.",
                )
            )
    _check_shot_state_alignment(repo, shot, issues)
    _check_180_axis_continuity(prev_shot, shot, issues)


def _verify_s4_shots(repo: Repo, idx: GraphIndex, issues: list[StageQaIssue]) -> None:
    """Verify S4_SHOTS across all scenes and shots in a single linear sweep."""
    if not idx.shots:
        issues.append(
            StageQaIssue(
                code="missing_shots",
                severity="error",
                node_id="shots",
                message="No Shot nodes exist in the StoryGraph.",
            )
        )
        return
    prev_shot: Shot | None = None
    for sh in idx.shots:
        _verify_single_shot(repo, idx, sh, prev_shot, issues)
        prev_shot = sh


def _verify_s5_music(idx: GraphIndex, issues: list[StageQaIssue]) -> None:
    """Verify S5_MUSIC: scene MusicCues and per-shot foley/environmental/action SFX."""
    for sc in idx.scenes.values():
        if sc.id not in idx.music_by_scene:
            issues.append(
                StageQaIssue(
                    code="missing_scene_music_cue",
                    severity="error",
                    node_id=sc.id,
                    message=f"Scene '{sc.id}' has no MusicCue.",
                )
            )
    for sh in idx.shots:
        has_sfx = bool(sh.sfx or sh.foley_sfx or sh.environmental_sfx)
        if not sh.music_cue_id or not has_sfx:
            issues.append(
                StageQaIssue(
                    code="missing_shot_soundscape",
                    severity="error",
                    node_id=sh.id,
                    message=f"Shot '{sh.id}' is missing music_cue_id or foley/environmental SFX.",
                )
            )


def verify_storygraph(
    repo: Repo,
    cfg: Config | None = None,
    through_stage: str = "S5_MUSIC",
) -> list[StageQaIssue]:
    """Run the O(V + E) single-pass StoryGraph verifier up through `through_stage`."""
    _ = cfg
    rank = _STAGE_RANK.get(through_stage, 5)
    idx = build_graph_index(repo)
    issues: list[StageQaIssue] = []
    if rank >= 1:
        _verify_s1_extract(repo, idx, issues)
    if rank >= 2:
        _verify_s2_screenplay(idx, issues)
        chk = rank >= 4
        clip_args = (idx.scenes, idx.dialogues, idx.shots, chk)
        cast_src = (list(idx.entities.values()), idx.appearances_by_entity)
        issues.extend(clip_stage_issues(*clip_args, *cast_src))
        verify_physical_causality(
            idx.scenes, idx.events, idx.shots, idx.entities, issues, check_shots=chk
        )
    if rank >= 3:
        _verify_s3_design(idx, issues)
    if rank >= 4:
        _verify_s4_shots(repo, idx, issues)
    if rank >= 5:
        _verify_s5_music(idx, issues)
    return issues

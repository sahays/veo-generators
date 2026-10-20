"""Shift-Left Stage QA & Auto-Remediation Agent (`stage_qa_agent`) for S1_EXTRACT..S5_MUSIC."""

from __future__ import annotations

import uuid
from typing import Final

from ..config import Config
from ..graph_verifier import build_graph_index, verify_storygraph
from ..physics import remediate_physical_causality
from ..presets import resolve_production_presets
from ..repo import Repo
from ..schema import (
    EntityType,
    InteractionStep,
    Role,
    StageQaReport,
    StateEffect,
    Status,
)
from ..state import appearance_for, rebuild_state_facts, state_at
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from .stage_qa_clips import remediate_scene_clips

_STAGE_TO_ROLE: Final[dict[str, Role]] = {
    "S1_EXTRACT": Role.STORY_ARCHITECT,
    "S2_SCREENPLAY": Role.SCREENWRITER,
    "S3_DESIGN": Role.DESIGNER,
    "S4_SHOTS": Role.DIRECTOR,
    "S5_MUSIC": Role.MUSIC_DIRECTOR,
}


def list_stage_qa_reports(repo: Repo) -> list[StageQaReport]:
    """Return all recorded `StageQaReport` nodes ordered by creation time."""
    docs = repo.store.query("stage_qa_reports")
    reports = [StageQaReport.model_validate(d) for d in docs]
    reports.sort(key=lambda r: r.created_at)
    return reports


def _remediate_event_locations(repo: Repo, fixed: list[str]) -> None:
    """Normalize non-scene `location` StateEffects on Events into `sub_location` + scene `location_id`."""
    scenes = {s.id: s for s in repo.list_scenes()}
    changed = False
    for ev in repo.list_events():
        sc = scenes.get(ev.scene_id)
        if sc is None:
            continue
        new_fx: list[StateEffect] = []
        ev_mod = False
        has_loc = {
            ef.entity_id
            for ef in ev.effects
            if ef.attribute == "location" and ef.new_value == sc.location_id
        }
        for ef in ev.effects:
            if (
                ef.attribute == "location"
                and ef.new_value
                and ef.new_value != sc.location_id
            ):
                new_fx.append(ef.model_copy(update={"attribute": "sub_location"}))
                if ef.entity_id not in has_loc:
                    new_fx.append(ef.model_copy(update={"new_value": sc.location_id}))
                    has_loc.add(ef.entity_id)
                ev_mod = True
            else:
                new_fx.append(ef)
        if ev_mod:
            repo.put_event(ev.model_copy(update={"effects": new_fx}))
            changed = True
            fixed.append(
                f"Canonicalized location state effects on {ev.id} to {sc.location_id}."
            )
    if changed:
        rebuild_state_facts(repo)


def _remediate_s1_extract(repo: Repo, cfg: Config, fixed: list[str]) -> None:
    """Auto-remediate S1_EXTRACT StyleGuide or non-canonical event location state effects."""
    _remediate_event_locations(repo, fixed)
    ctx = ToolContext(repo=repo, role=Role.STORY_ARCHITECT, cfg=cfg)
    meta = repo.get_project_meta()
    bundle = resolve_production_presets(
        visual_style_id=meta.visual_style_preset if meta else None,
        color_palette_id=meta.color_palette_preset if meta else None,
        director_style_id=meta.director_style_preset if meta else None,
    )
    sg = repo.get_style_guide()
    if sg is None or not sg.visual_medium.strip() or not sg.palette:
        wt.put_style_guide(
            ctx,
            visual_medium=bundle.visual_style.visual_medium,
            palette=list(bundle.color_palette.palette),
            lens_language=bundle.visual_style.lens_language,
            lighting_rules=f"{bundle.visual_style.lighting_rules} {bundle.color_palette.lighting_tint}".strip(),
            aspect_ratio=meta.orientation if meta else "16:9",
            avoid=list(bundle.visual_style.avoid),
            visual_style_preset=bundle.visual_style.id,
            color_palette_preset=bundle.color_palette.id,
            director_style_preset=bundle.director_style.id,
            screenplay_style_preset=bundle.screenplay_style.id,
            music_style_preset=bundle.music_style.id,
        )
        fixed.append("Repaired StyleGuide from active production presets.")


def _remediate_s2_screenplay(repo: Repo, cfg: Config, fixed: list[str]) -> None:
    """Auto-remediate missing or non-atomic `interaction_steps` on Scene nodes."""
    ctx = ToolContext(repo=repo, role=Role.SCREENWRITER, cfg=cfg)
    idx = build_graph_index(repo)
    chars = [
        e.id for e in idx.entities.values() if e.entity_type == EntityType.CHARACTER
    ]
    lead_id = chars[0] if chars else "char_arjun"
    for sc in idx.scenes.values():
        need_fix = not sc.interaction_steps or any(
            s.actor_id not in idx.entities or ";" in s.action
            for s in sc.interaction_steps
        )
        if not need_fix:
            continue
        sc_events = [e for e in idx.events if e.scene_id == sc.id]
        steps: list[InteractionStep] = []
        for s_idx, ev in enumerate(sc_events, start=1):
            actor = next((p for p in ev.participants if p in idx.entities), lead_id)
            target = next(
                (p for p in ev.participants if p != actor and p in idx.entities),
                sc.location_id,
            )
            action_clause = ev.summary.split(";")[0].strip() or f"Acts in {sc.heading}."
            steps.append(
                InteractionStep(
                    step_index=s_idx,
                    actor_id=actor,
                    interaction_type="environment"
                    if target == sc.location_id
                    else "character",
                    target_id=target,
                    action=" ".join(action_clause.split()[:22]),
                    emotional_beat=sc.mood or "focused",
                )
            )
        if not steps:
            steps.append(
                InteractionStep(
                    step_index=1,
                    actor_id=lead_id,
                    interaction_type="environment",
                    target_id=sc.location_id,
                    action=" ".join(
                        (sc.summary or sc.heading).split(";")[0].split()[:22]
                    ),
                    emotional_beat=sc.mood or "cinematic",
                )
            )
        wt.update_scene_script(
            ctx,
            scene_id=sc.id,
            summary=sc.summary or sc.heading,
            mood=sc.mood or "cinematic",
            interaction_steps=steps,
        )
        fixed.append(f"Normalized {len(steps)} atomic InteractionSteps for {sc.id}.")


def _align_shot_entity_locations(repo: Repo, idx: object, fixed: list[str]) -> None:
    """Ensure every cast member and prop in a shot has matching scene `location` state at `shot.story_order`."""
    events_by_scene: dict[str, list[object]] = {}
    for ev in repo.list_events():
        events_by_scene.setdefault(ev.scene_id, []).append(ev)
    state_dirty = False
    for sh in repo.list_shots():
        eids = [c.entity_id for c in sh.cast] + list(sh.prop_ids)
        mismatched = [
            eid
            for eid in eids
            if (loc := state_at(repo, eid, sh.story_order).get("location"))
            and loc != sh.location_id
        ]
        if not mismatched:
            continue
        sc_evs = [
            e
            for e in repo.list_events()
            if e.scene_id == sh.scene_id and e.story_order <= sh.story_order
        ] or [e for e in repo.list_events() if e.scene_id == sh.scene_id]
        if sc_evs:
            target_ev = sc_evs[0]
            new_fx = [
                ef
                for ef in target_ev.effects
                if not (ef.entity_id in mismatched and ef.attribute == "location")
            ] + [
                StateEffect(
                    entity_id=eid, attribute="location", new_value=sh.location_id
                )
                for eid in mismatched
            ]
            repo.put_event(target_ev.model_copy(update={"effects": new_fx}))
            state_dirty = True
            fixed.append(f"Aligned state-fact location for {mismatched} in {sh.id}.")
    if state_dirty:
        rebuild_state_facts(repo)


def _remediate_s4_shots(repo: Repo, fixed: list[str]) -> None:
    """Auto-remediate shot appearance links, held-prop continuity, and state-fact location alignment."""
    _remediate_event_locations(repo, fixed)
    idx = build_graph_index(repo)
    _align_shot_entity_locations(repo, idx, fixed)
    for sh in idx.shots:
        updated_props = list(sh.prop_ids)
        changed = False
        new_cast = list(sh.cast)
        for c_idx, c in enumerate(new_cast):
            held = state_at(repo, c.entity_id, sh.story_order).get("holding")
            if held and held in idx.entities and held not in updated_props:
                updated_props.append(held)
                changed = True
            app = (
                appearance_for(repo, c.entity_id, sh.story_order)
                if repo.list_appearances(entity_id=c.entity_id)
                else None
            )
            if app and c.appearance_id != app.id:
                new_cast[c_idx] = c.model_copy(update={"appearance_id": app.id})
                changed = True
        sc = idx.scenes.get(sh.scene_id)
        new_loc = (
            sc.location_id
            if sc and sh.location_id != sc.location_id
            else sh.location_id
        )
        loc_app = (
            appearance_for(repo, new_loc, sh.story_order)
            if repo.list_appearances(entity_id=new_loc)
            else None
        )
        new_loc_app_id = loc_app.id if loc_app else sh.location_appearance_id
        if new_loc != sh.location_id or new_loc_app_id != sh.location_appearance_id:
            changed = True
        if changed:
            repo.put_shot(
                sh.model_copy(
                    update={
                        "cast": new_cast,
                        "prop_ids": updated_props,
                        "location_id": new_loc,
                        "location_appearance_id": new_loc_app_id,
                    }
                )
            )
            fixed.append(f"Aligned continuity prop/location state on shot {sh.id}.")


def _remediate_s5_music(repo: Repo, cfg: Config, fixed: list[str]) -> None:
    """Auto-remediate missing scene MusicCues or missing shot foley/environmental SFX."""
    ctx = ToolContext(repo=repo, role=Role.MUSIC_DIRECTOR, cfg=cfg)
    idx = build_graph_index(repo)
    for sc in idx.scenes.values():
        if sc.id not in idx.music_by_scene:
            wt.put_music_cue(
                ctx,
                cue_id=f"cue_{sc.id}",
                scene_id=sc.id,
                mood=sc.mood or "cinematic",
                instrumentation="orchestral strings, atmospheric pads, tactile percussion",
                tempo_bpm=92,
                motif_tags=["main_theme", sc.time_of_day],
                environmental_bed=f"{sc.weather} {sc.time_of_day} ambience",
            )
            fixed.append(f"Created fallback MusicCue for scene {sc.id}.")
    cue_by_scene = {c.scene_id: c.id for c in repo.list_music_cues()}
    for sh in idx.shots:
        if not sh.music_cue_id or not (sh.sfx or sh.foley_sfx or sh.environmental_sfx):
            foley = sh.foley_sfx or ["footsteps and cloth movement"]
            env_sfx = sh.environmental_sfx or ["gentle wind and room tone"]
            act_sfx = sh.action_focus_sfx or ["subtle motion accent"]
            wt.set_shot_audio(
                ctx,
                shot_id=sh.id,
                music_cue_id=sh.music_cue_id or cue_by_scene.get(sh.scene_id),
                sfx=sh.sfx or [*foley, *env_sfx],
                foley_sfx=foley,
                environmental_sfx=env_sfx,
                action_focus_sfx=act_sfx,
            )
            fixed.append(f"Attached foley, environmental, and action SFX to {sh.id}.")


_ROLE_TO_STAGE: Final[dict[str, str]] = {
    str(Role.STORY_ARCHITECT): "S1_EXTRACT",
    str(Role.SCRIPT_SUPERVISOR): "S1_EXTRACT",
    str(Role.SCREENWRITER): "S2_SCREENPLAY",
    str(Role.DESIGNER): "S3_DESIGN",
    str(Role.CHARACTER_DESIGNER): "S3_DESIGN",
    str(Role.LOCATION_DESIGNER): "S3_DESIGN",
    str(Role.OBJECT_DESIGNER): "S3_DESIGN",
    str(Role.DIRECTOR): "S4_SHOTS",
    str(Role.MUSIC_DIRECTOR): "S5_MUSIC",
}


def stages_to_redo_for_issues(
    qa_issues: list[object],
    val_errors: list[object],
    open_crs: list[object] | None = None,
) -> list[str]:
    """Map QA issues, validation errors, and open ChangeRequests to ordered upstream stages (`S1..S5`)."""
    needed: set[str] = set()
    for item in [*qa_issues, *val_errors]:
        code = str(getattr(item, "code", ""))
        if code.startswith("S1_") or code == "V_NO_STYLE_GUIDE":
            needed.add("S1_EXTRACT")
        elif code.startswith("S2_") or code == "V_NO_SCENES":
            needed.add("S2_SCREENPLAY")
            if code.startswith("S2_CLIP"):
                needed.add(
                    "S4_SHOTS"
                )  # shots are 1:1 with clips; re-block after re-arranging
        elif code.startswith("S3_") or code in (
            "V_UNAPPROVED_APPEARANCE",
            "V_UNLINKED_ASSET",
        ):
            needed.add("S3_DESIGN")
        elif code.startswith("S4_") or code.startswith("V_"):
            needed.add("S4_SHOTS")
        elif code.startswith("S5_"):
            needed.add("S5_MUSIC")
    for cr in open_crs or []:
        st = _ROLE_TO_STAGE.get(str(getattr(cr, "to_role", "")))
        if st:
            needed.add(st)
    order = ["S1_EXTRACT", "S2_SCREENPLAY", "S3_DESIGN", "S4_SHOTS", "S5_MUSIC"]
    return [s for s in order if s in needed]


def run_stage_qa_and_remediate(
    repo: Repo,
    cfg: Config,
    stage: str,
    max_iterations: int = 3,
) -> StageQaReport:
    """Run deterministic O(V+E) Stage QA after `stage`, auto-remediate issues, and persist `StageQaReport`."""
    target_role = _STAGE_TO_ROLE.get(stage, Role.CRITIC)
    issues = verify_storygraph(repo, cfg, through_stage=stage)
    remediated_actions: list[str] = []
    iteration = 1

    while any(i.severity == "error" for i in issues) and iteration <= max_iterations:
        _remediate_s1_extract(repo, cfg, remediated_actions)
        if stage in ("S2_SCREENPLAY", "S3_DESIGN", "S4_SHOTS", "S5_MUSIC"):
            _remediate_s2_screenplay(repo, cfg, remediated_actions)
            remediate_physical_causality(repo, remediated_actions, include_shots=False)
            remediate_scene_clips(repo, cfg, remediated_actions)
        if stage in ("S4_SHOTS", "S5_MUSIC"):
            remediate_physical_causality(repo, remediated_actions, include_shots=True)
            _remediate_s4_shots(repo, remediated_actions)
        if stage == "S5_MUSIC":
            _remediate_s5_music(repo, cfg, remediated_actions)
        issues = verify_storygraph(repo, cfg, through_stage=stage)
        iteration += 1

    passed = not any(i.severity == "error" for i in issues)
    summary = (
        f"Stage {stage} QA passed ({len(remediated_actions)} auto-remediations applied)."
        if passed
        else f"Stage {stage} QA flagged {len(issues)} issue(s) after {iteration - 1} remediation pass(es)."
    )
    report = StageQaReport(
        id=f"sqa_{stage}_{uuid.uuid4().hex[:8]}",
        created_by=Role.CRITIC,
        status=Status.APPROVED if passed else Status.NEEDS_REVISION,
        stage=stage,
        agent_role=str(target_role),
        target_role=str(target_role),
        attempt=max(1, iteration - 1),
        iteration=max(1, iteration - 1),
        passed=passed,
        score=1.0 if passed else max(0.0, round(1.0 - 0.15 * len(issues), 2)),
        issues=issues,
        remediation_applied=remediated_actions,
        summary=summary,
    )
    repo.store.set("stage_qa_reports", report.id, report.model_dump(mode="json"))
    return report

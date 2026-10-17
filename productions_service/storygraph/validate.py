"""Deterministic StoryGraph Validator implementing rules V1 through V13."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import Config
from .repo import Repo
from .schema import Shot, Status
from .state import state_at


@dataclass(frozen=True)
class ValidationIssue:
    code: str  # "V1".."V13"
    severity: Literal["error", "warn"]
    node_id: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "node_id": self.node_id,
            "message": self.message,
        }


def _check_appearance_and_asset(
    repo: Repo,
    shot_id: str,
    entity_id: str,
    appearance_id: str,
    entity_label: str,
    issues: list[ValidationIssue],
) -> None:
    if not appearance_id:
        msg = f"{entity_label} '{entity_id}' in shot '{shot_id}' has no resolved appearance_id"
        issues.append(ValidationIssue("V1", "error", shot_id, msg))
        return
    app = repo.get_appearance(appearance_id)
    if not app or app.status != Status.APPROVED:
        msg = f"Appearance '{appearance_id}' for {entity_label} '{entity_id}' is not APPROVED"
        issues.append(ValidationIssue("V1", "error", shot_id, msg))
        return
    if not app.asset_ids:
        msg = f"Appearance '{appearance_id}' for {entity_label} '{entity_id}' has no linked reference image Asset"
        issues.append(ValidationIssue("V1", "error", shot_id, msg))
        return
    has_approved = any(
        (asset := repo.get_asset(aid)) is not None and asset.status == Status.APPROVED
        for aid in app.asset_ids
    )
    if not has_approved:
        msg = f"Appearance '{appearance_id}' has no APPROVED reference image Asset"
        issues.append(ValidationIssue("V1", "error", shot_id, msg))


def _check_v1_appearances(
    repo: Repo, shot: Shot, issues: list[ValidationIssue]
) -> None:
    if shot.location_id:
        _check_appearance_and_asset(
            repo,
            shot.id,
            shot.location_id,
            shot.location_appearance_id,
            "Location",
            issues,
        )
    for cast_item in shot.cast:
        _check_appearance_and_asset(
            repo,
            shot.id,
            cast_item.entity_id,
            cast_item.appearance_id,
            "Character",
            issues,
        )
    for pid in shot.prop_ids:
        _check_appearance_and_asset(
            repo,
            shot.id,
            pid,
            shot.prop_appearance_ids.get(pid, ""),
            "Prop/Object",
            issues,
        )


def _check_v2_v3_v5_cast_states(
    repo: Repo, shot: Shot, issues: list[ValidationIssue]
) -> None:
    for cast_item in shot.cast:
        st = state_at(repo, cast_item.entity_id, shot.story_order)
        wearing = st.get("wearing")
        if wearing and cast_item.appearance_id:
            app = repo.get_appearance(cast_item.appearance_id)
            if app and app.state_label != wearing:
                msg = (
                    f"Cast '{cast_item.entity_id}' wears '{wearing}' at order {shot.story_order}, "
                    f"but shot uses appearance state_label '{app.state_label}'"
                )
                issues.append(ValidationIssue("V2", "error", shot.id, msg))
        ent_loc = st.get("location")
        if ent_loc and ent_loc != shot.location_id:
            msg = (
                f"Cast '{cast_item.entity_id}' is at location '{ent_loc}' at order {shot.story_order}, "
                f"not shot location '{shot.location_id}'"
            )
            issues.append(ValidationIssue("V3", "error", shot.id, msg))
        if st.get("alive_present") == "false":
            msg = f"Cast '{cast_item.entity_id}' has alive_present=='false' at order {shot.story_order}"
            issues.append(ValidationIssue("V5", "error", shot.id, msg))


def _check_v4_props(repo: Repo, shot: Shot, issues: list[ValidationIssue]) -> None:
    held_props = {
        held
        for c in shot.cast
        if (held := state_at(repo, c.entity_id, shot.story_order).get("holding"))
    }
    for pid in shot.prop_ids:
        p_loc = state_at(repo, pid, shot.story_order).get("location")
        if p_loc and p_loc != shot.location_id and pid not in held_props:
            msg = f"Prop '{pid}' is at '{p_loc}' and not held by any cast member in shot '{shot.id}'"
            issues.append(ValidationIssue("V4", "error", shot.id, msg))


def _check_v6_v7_timing(shot: Shot, cfg: Config, issues: list[ValidationIssue]) -> None:
    if shot.duration_s <= 0 or shot.duration_s > cfg.video.max_duration_s:
        msg = f"Shot duration {shot.duration_s}s outside valid range (0, {cfg.video.max_duration_s}]"
        issues.append(ValidationIssue("V6", "error", shot.id, msg))
    last_end = 0.0
    for idx, beat in enumerate(shot.beats):
        if beat.t_start_s < 0 or beat.t_end_s > shot.duration_s + 1e-6:
            msg = f"ActionBeat {idx} [{beat.t_start_s}, {beat.t_end_s}] exceeds [0, {shot.duration_s}]"
            issues.append(ValidationIssue("V7", "error", shot.id, msg))
        if beat.t_end_s <= beat.t_start_s:
            msg = f"ActionBeat {idx} has non-positive duration [{beat.t_start_s}, {beat.t_end_s}]"
            issues.append(ValidationIssue("V7", "error", shot.id, msg))
        if beat.t_start_s < last_end - 1e-6:
            msg = f"ActionBeat {idx} overlaps previous beat (starts at {beat.t_start_s} < {last_end})"
            issues.append(ValidationIssue("V7", "error", shot.id, msg))
        last_end = max(last_end, beat.t_end_s)


def _check_v8_v9_dialogue(
    repo: Repo, shot: Shot, cfg: Config, issues: list[ValidationIssue]
) -> None:
    total_words = 0
    for did in shot.dialogue_ids:
        dline = repo.get_dialogue(did)
        if dline:
            total_words += len(dline.text.split())
            if not any(c.entity_id == dline.speaker_id for c in shot.cast):
                msg = f"DialogueLine '{dline.id}' speaker '{dline.speaker_id}' is not in shot '{shot.id}' cast"
                issues.append(ValidationIssue("V9", "error", shot.id, msg))
    if shot.duration_s > 0:
        wps = total_words / shot.duration_s
        if wps > cfg.caps.max_words_per_sec:
            msg = f"Shot '{shot.id}' speech rate {wps:.2f} words/s exceeds cap {cfg.caps.max_words_per_sec}"
            issues.append(ValidationIssue("V8", "error", shot.id, msg))


def validate_shot(
    repo: Repo,
    shot: Shot,
    cfg: Config,
    prev_shot: Shot | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _check_v1_appearances(repo, shot, issues)
    _check_v2_v3_v5_cast_states(repo, shot, issues)
    _check_v4_props(repo, shot, issues)
    _check_v6_v7_timing(shot, cfg, issues)
    _check_v8_v9_dialogue(repo, shot, cfg, issues)
    if shot.continue_from_last_frame and (
        prev_shot is None or prev_shot.location_id != shot.location_id
    ):
        msg = f"Shot '{shot.id}' has continue_from_last_frame=True without matching previous shot location"
        issues.append(ValidationIssue("V11", "warn", shot.id, msg))
    if shot.stale:
        msg = f"Shot '{shot.id}' is marked stale ({shot.stale_reason or 'upstream asset changed'})"
        issues.append(ValidationIssue("V13", "error", shot.id, msg))
    return issues


def _check_v12_entities(repo: Repo, issues: list[ValidationIssue]) -> None:
    alias_owners: dict[str, str] = {}
    for ent in repo.list_entities():
        if not ent.canonical_name.strip():
            issues.append(
                ValidationIssue(
                    "V12",
                    "error",
                    ent.id,
                    f"Entity '{ent.id}' has an empty canonical_name",
                )
            )
        for alias in [ent.canonical_name, *ent.aliases]:
            norm = alias.strip().lower()
            if not norm:
                continue
            prev_owner = alias_owners.get(norm)
            if prev_owner and prev_owner != ent.id:
                msg = f"Alias/name '{alias}' on '{ent.id}' duplicates entity '{prev_owner}'"
                issues.append(ValidationIssue("V12", "error", ent.id, msg))
            else:
                alias_owners[norm] = ent.id


def validate_all(repo: Repo, cfg: Config) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _check_v12_entities(repo, issues)
    shots = sorted(
        repo.list_shots(), key=lambda s: (s.story_order, s.scene_id, s.index_in_scene)
    )
    covered_events: set[str] = set()
    prev_shot: Shot | None = None
    for s in shots:
        covered_events.update(s.covers_event_ids)
        issues.extend(validate_shot(repo, s, cfg, prev_shot=prev_shot))
        prev_shot = s
    for ev in repo.list_events():
        if ev.id not in covered_events:
            msg = f"Event '{ev.id}' (order {ev.story_order}) is not covered by any Shot"
            issues.append(ValidationIssue("V10", "warn", ev.id, msg))
    return issues

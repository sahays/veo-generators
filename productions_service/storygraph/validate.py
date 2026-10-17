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
        issues.append(
            ValidationIssue(
                "V1",
                "error",
                shot_id,
                f"{entity_label} '{entity_id}' in shot '{shot_id}' has no resolved appearance_id",
            )
        )
        return
    app = repo.get_appearance(appearance_id)
    if not app or app.status != Status.APPROVED:
        issues.append(
            ValidationIssue(
                "V1",
                "error",
                shot_id,
                f"Appearance '{appearance_id}' for {entity_label} '{entity_id}' is not APPROVED",
            )
        )
        return
    if not app.asset_ids:
        issues.append(
            ValidationIssue(
                "V1",
                "error",
                shot_id,
                f"Appearance '{appearance_id}' for {entity_label} '{entity_id}' has no linked reference image Asset",
            )
        )
        return
    has_approved_asset = False
    for aid in app.asset_ids:
        asset = repo.get_asset(aid)
        if asset and asset.status == Status.APPROVED:
            has_approved_asset = True
            break
    if not has_approved_asset:
        issues.append(
            ValidationIssue(
                "V1",
                "error",
                shot_id,
                f"Appearance '{appearance_id}' has no APPROVED reference image Asset",
            )
        )


def validate_shot(
    repo: Repo,
    shot: Shot,
    cfg: Config,
    prev_shot: Shot | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # V1: Every cast.entity_id, location_id, and prop_ids in Shot has an APPROVED Appearance with >=1 APPROVED Asset
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

    # V2: Shot.cast[i].appearance_id matches state_at(entity, shot.story_order)["wearing"] if such StateFact exists
    for cast_item in shot.cast:
        st = state_at(repo, cast_item.entity_id, shot.story_order)
        wearing = st.get("wearing")
        if wearing and cast_item.appearance_id:
            app = repo.get_appearance(cast_item.appearance_id)
            if app and app.state_label != wearing:
                issues.append(
                    ValidationIssue(
                        "V2",
                        "error",
                        shot.id,
                        f"Cast '{cast_item.entity_id}' wears '{wearing}' at order {shot.story_order}, "
                        f"but shot uses appearance state_label '{app.state_label}'",
                    )
                )

    # V3: All cast in Shot have state_at.location == shot.location_id (when location fact exists)
    for cast_item in shot.cast:
        st = state_at(repo, cast_item.entity_id, shot.story_order)
        ent_loc = st.get("location")
        if ent_loc and ent_loc != shot.location_id:
            issues.append(
                ValidationIssue(
                    "V3",
                    "error",
                    shot.id,
                    f"Cast '{cast_item.entity_id}' is at location '{ent_loc}' at order {shot.story_order}, "
                    f"not shot location '{shot.location_id}'",
                )
            )

    # V4: Every prop in Shot.prop_ids is either at shot.location_id or held by a cast member in the shot
    cast_ids = {c.entity_id for c in shot.cast}
    held_props = set()
    for cid in cast_ids:
        st = state_at(repo, cid, shot.story_order)
        if st.get("holding"):
            held_props.add(st["holding"])
    for pid in shot.prop_ids:
        pst = state_at(repo, pid, shot.story_order)
        p_loc = pst.get("location")
        if p_loc and p_loc != shot.location_id and pid not in held_props:
            issues.append(
                ValidationIssue(
                    "V4",
                    "error",
                    shot.id,
                    f"Prop '{pid}' is at '{p_loc}' and not held by any cast member in shot '{shot.id}'",
                )
            )

    # V5: Entity with alive_present == "false" at shot.story_order cannot appear in cast
    for cast_item in shot.cast:
        st = state_at(repo, cast_item.entity_id, shot.story_order)
        if st.get("alive_present") == "false":
            issues.append(
                ValidationIssue(
                    "V5",
                    "error",
                    shot.id,
                    f"Cast '{cast_item.entity_id}' has alive_present=='false' at order {shot.story_order}",
                )
            )

    # V6: 0 < shot.duration_s <= cfg.video.max_duration_s
    if shot.duration_s <= 0 or shot.duration_s > cfg.video.max_duration_s:
        issues.append(
            ValidationIssue(
                "V6",
                "error",
                shot.id,
                f"Shot duration {shot.duration_s}s outside valid range (0, {cfg.video.max_duration_s}]",
            )
        )

    # V7: ActionBeats lie within [0, duration_s], non-overlapping, sorted
    last_end = 0.0
    for idx, beat in enumerate(shot.beats):
        if beat.t_start_s < 0 or beat.t_end_s > shot.duration_s + 1e-6:
            issues.append(
                ValidationIssue(
                    "V7",
                    "error",
                    shot.id,
                    f"ActionBeat {idx} [{beat.t_start_s}, {beat.t_end_s}] exceeds [0, {shot.duration_s}]",
                )
            )
        if beat.t_end_s <= beat.t_start_s:
            issues.append(
                ValidationIssue(
                    "V7",
                    "error",
                    shot.id,
                    f"ActionBeat {idx} has non-positive duration [{beat.t_start_s}, {beat.t_end_s}]",
                )
            )
        if beat.t_start_s < last_end - 1e-6:
            issues.append(
                ValidationIssue(
                    "V7",
                    "error",
                    shot.id,
                    f"ActionBeat {idx} overlaps previous beat (starts at {beat.t_start_s} < {last_end})",
                )
            )
        last_end = max(last_end, beat.t_end_s)

    # V8: Spoken word count across dialogue_ids / duration_s <= cfg.caps.max_words_per_sec
    total_words = 0
    for did in shot.dialogue_ids:
        dline = repo.get_dialogue(did)
        if dline:
            total_words += len(dline.text.split())
            # V9: DialogueLine.speaker_id is in cast (or position == "offscreen_voice")
            speaker_in_cast = any(c.entity_id == dline.speaker_id for c in shot.cast)
            if not speaker_in_cast:
                issues.append(
                    ValidationIssue(
                        "V9",
                        "error",
                        shot.id,
                        f"DialogueLine '{dline.id}' speaker '{dline.speaker_id}' is not in shot '{shot.id}' cast",
                    )
                )
    if shot.duration_s > 0:
        wps = total_words / shot.duration_s
        if wps > cfg.caps.max_words_per_sec:
            issues.append(
                ValidationIssue(
                    "V8",
                    "error",
                    shot.id,
                    f"Shot '{shot.id}' speech rate {wps:.2f} words/s exceeds cap {cfg.caps.max_words_per_sec}",
                )
            )

    # V11: If continue_from_last_frame == True, previous shot must share location_id
    if shot.continue_from_last_frame:
        if prev_shot is None or prev_shot.location_id != shot.location_id:
            issues.append(
                ValidationIssue(
                    "V11",
                    "warn",
                    shot.id,
                    f"Shot '{shot.id}' has continue_from_last_frame=True without matching previous shot location",
                )
            )

    # V13: Shot.stale == False
    if shot.stale:
        issues.append(
            ValidationIssue(
                "V13",
                "error",
                shot.id,
                f"Shot '{shot.id}' is marked stale ({shot.stale_reason or 'upstream asset changed'})",
            )
        )

    return issues


def validate_all(repo: Repo, cfg: Config) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    # V12: Every Entity has non-empty canonical_name and no duplicate aliases across entities
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
        all_names = [ent.canonical_name, *ent.aliases]
        for alias in all_names:
            norm = alias.strip().lower()
            if not norm:
                continue
            prev_owner = alias_owners.get(norm)
            if prev_owner and prev_owner != ent.id:
                issues.append(
                    ValidationIssue(
                        "V12",
                        "error",
                        ent.id,
                        f"Alias/name '{alias}' on '{ent.id}' duplicates entity '{prev_owner}'",
                    )
                )
            else:
                alias_owners[norm] = ent.id

    shots = sorted(
        repo.list_shots(), key=lambda s: (s.story_order, s.scene_id, s.index_in_scene)
    )
    covered_events: set[str] = set()
    prev_shot: Shot | None = None
    for s in shots:
        covered_events.update(s.covers_event_ids)
        issues.extend(validate_shot(repo, s, cfg, prev_shot=prev_shot))
        prev_shot = s

    # V10: Every Event is covered by >= 1 Shot.covers_event_ids
    for ev in repo.list_events():
        if ev.id not in covered_events:
            issues.append(
                ValidationIssue(
                    "V10",
                    "warn",
                    ev.id,
                    f"Event '{ev.id}' (order {ev.story_order}) is not covered by any Shot",
                )
            )

    return issues

"""Permissioned music cue, shot audio, asset critique, clip QA, and change-request write tools."""

from __future__ import annotations

import uuid
from typing import Any

from ...audit import append_audit
from ...errors import NotFound
from ...schema import ChangeRequest, MusicCue, QAReport, Role, Status
from ..registry import ToolContext, assert_can_write


def put_music_cue(
    ctx: ToolContext,
    cue_id: str,
    scene_id: str,
    mood: str,
    instrumentation: str,
    tempo_bpm: int,
    motif_tags: list[str] | None = None,
    environmental_bed: str = "",
    audio_asset_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "MusicCue")
    prev = ctx.repo.get_music_cue(cue_id)
    cue = MusicCue(
        id=cue_id,
        created_by=ctx.role,
        status=Status.APPROVED,
        scene_id=scene_id,
        mood=mood,
        instrumentation=instrumentation,
        tempo_bpm=tempo_bpm,
        motif_tags=motif_tags or [],
        environmental_bed=environmental_bed,
        audio_asset_id=audio_asset_id,
    )
    saved = ctx.repo.put_music_cue(cue)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "put_music_cue",
        saved.id,
        prev.version if prev else None,
        saved.version,
        f"Music cue '{saved.id}' ({mood}, {tempo_bpm}bpm)",
    )
    return saved.model_dump(mode="json")


def set_shot_audio(
    ctx: ToolContext,
    shot_id: str,
    music_cue_id: str | None,
    sfx: list[str],
    foley_sfx: list[str] | None = None,
    environmental_sfx: list[str] | None = None,
    action_focus_sfx: list[str] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Shot.music_cue_id")
    assert_can_write(ctx.role, "Shot.sfx")
    prev = ctx.repo.get_shot(shot_id)
    if not prev:
        raise NotFound(f"Shot {shot_id} not found")
    merged_sfx = list(
        dict.fromkeys(
            [
                *sfx,
                *(foley_sfx or []),
                *(environmental_sfx or []),
                *(action_focus_sfx or []),
            ]
        )
    )
    updated = prev.model_copy(
        update={
            "music_cue_id": music_cue_id,
            "sfx": merged_sfx,
            "foley_sfx": foley_sfx if foley_sfx is not None else prev.foley_sfx,
            "environmental_sfx": (
                environmental_sfx
                if environmental_sfx is not None
                else prev.environmental_sfx
            ),
            "action_focus_sfx": (
                action_focus_sfx
                if action_focus_sfx is not None
                else prev.action_focus_sfx
            ),
        }
    )
    saved = ctx.repo.put_shot(updated)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "set_shot_audio",
        saved.id,
        prev.version,
        saved.version,
        f"Set audio on shot '{shot_id}' (cue={music_cue_id}, sfx={len(merged_sfx)})",
    )
    return saved.model_dump(mode="json")


def record_asset_critique(
    ctx: ToolContext, asset_id: str, approved: bool, qa_notes: str
) -> dict[str, Any]:
    assert_can_write(ctx.role, "Asset.qa_notes")
    prev = ctx.repo.get_asset(asset_id)
    if not prev:
        raise NotFound(f"Asset {asset_id} not found")
    new_status = Status.APPROVED if approved else Status.PROPOSED
    saved = ctx.repo.update_asset(asset_id, status=new_status, qa_notes=qa_notes)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "record_asset_critique",
        saved.id,
        prev.version,
        saved.version,
        f"Critic asset review: approved={approved}",
    )
    return saved.model_dump(mode="json")


def record_clip_qa(
    ctx: ToolContext,
    run_id: str,
    qa_report: QAReport | dict[str, Any],
    extracted_last_frame_asset_id: str | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "GenerationRun.qa_scores")
    assert_can_write(ctx.role, "GenerationRun.status")
    report = (
        qa_report
        if isinstance(qa_report, QAReport)
        else QAReport.model_validate(qa_report)
    )
    status = Status.APPROVED if report.passed else Status.FAILED
    saved = ctx.repo.update_generation_run_qa(
        run_id=run_id,
        qa_scores=report,
        status=status,
        extracted_last_frame_asset_id=extracted_last_frame_asset_id,
    )
    append_audit(
        ctx.repo.store,
        ctx.role,
        "record_clip_qa",
        saved.id,
        saved.version - 1,
        saved.version,
        f"Clip QA on {run_id}: passed={report.passed}",
    )
    return saved.model_dump(mode="json")


def create_change_request(
    ctx: ToolContext,
    to_role: str | Role,
    target_node_id: str,
    reason: str,
    proposed_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert_can_write(ctx.role, "ChangeRequest")
    cr = ChangeRequest(
        id=f"cr_{uuid.uuid4().hex[:10]}",
        created_by=ctx.role,
        status=Status.PROPOSED,
        from_role=ctx.role,
        to_role=Role(to_role),
        target_node_id=target_node_id,
        reason=reason,
        proposed_patch=proposed_patch or {},
    )
    saved = ctx.repo.add_change_request(cr)
    append_audit(
        ctx.repo.store,
        ctx.role,
        "create_change_request",
        saved.id,
        None,
        saved.version,
        f"ChangeRequest {ctx.role} -> {to_role} on {target_node_id}",
    )
    return saved.model_dump(mode="json")

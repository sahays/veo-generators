"""CRITIC agent (`critic_agent`) for Stage S3 Visual Asset QA and Stage S9 Multimodal Clip QA."""

from __future__ import annotations

from pydantic import BaseModel

from ..adapters.base import VLMProvider
from ..adapters.media_frames import (
    detect_frame_anomalies,
    extract_representative_frames_png,
)
from ..config import Config
from ..repo import Repo
from ..schema import GenerationRun, QAReport, Role, Shot, Status
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import ShotView, shot_view

_extract_representative_frames_png = extract_representative_frames_png


class AssetCritiqueOutput(BaseModel):
    approved: bool = True
    qa_notes: str = "Visual reference matches StyleGuide and Appearance."
    refined_visual_description: str | None = None


def _safe_blob_bytes(repo: Repo, uri: str | None, fallback: bytes = b"") -> bytes:
    """Read blob bytes for `uri`, returning `fallback` if missing or unreadable."""
    if not uri:
        return fallback
    try:
        return repo.blobs.get_bytes(uri)
    except Exception:  # noqa: BLE001
        return fallback


def review_visual_asset(
    ctx: ToolContext,
    vlm: VLMProvider,
    asset_id: str,
    appearance_id: str,
) -> AssetCritiqueOutput:
    """Inspect a generated Character, Location, or Object reference sheet against its Appearance & StyleGuide."""
    asset = ctx.repo.get_asset(asset_id)
    app = ctx.repo.get_appearance(appearance_id)
    sg = ctx.repo.get_style_guide()
    if not asset or not app:
        return AssetCritiqueOutput(
            approved=False, qa_notes="Missing asset or appearance"
        )

    img_bytes = _safe_blob_bytes(ctx.repo, asset.uri)
    prompt = (
        f"Review reference asset {asset.id} ({asset.kind}) for appearance {app.id}: "
        f"'{app.visual_description}' (wardrobe: {app.wardrobe}). "
        f"StyleGuide: {sg.visual_medium if sg else 'cinematic'}."
    )
    critique = vlm.review(
        images=[img_bytes] if img_bytes else [],
        prompt=prompt,
        schema=AssetCritiqueOutput,
    )
    wt.record_asset_critique(
        ctx, asset_id=asset_id, approved=critique.approved, qa_notes=critique.qa_notes
    )
    if critique.approved:
        ctx.repo.update_appearance_status(appearance_id, Status.APPROVED)
    return critique


def _norm01(v: float) -> float:
    """Normalize a VLM similarity score from 0..100 or 0..10 into `[0.0, 1.0]`."""
    if v > 10.0:
        return min(1.0, max(0.0, round(v / 100.0, 3)))
    if v > 1.0:
        return min(1.0, max(0.0, round(v / 10.0, 3)))
    return max(0.0, v)


def _load_clip_and_ref_images(
    repo: Repo, run: GenerationRun
) -> tuple[list[bytes], list[bytes]]:
    """Extract representative frames from `run` and append reference asset images."""
    clip_bytes = _safe_blob_bytes(repo, run.output_video_uri, fallback=b"mock_mp4")
    frames = extract_representative_frames_png(clip_bytes)
    ref_images: list[bytes] = list(frames)
    for aid in run.reference_asset_ids:
        ref_asset = repo.get_asset(aid)
        if ref_asset:
            raw = _safe_blob_bytes(repo, ref_asset.uri)
            if raw:
                ref_images.append(raw)
    return frames, ref_images


_SEVERE_EXACT_FLAGS = {
    "style_drift",
    "anatomy_glitch",
    "text_overlay",
    "frozen_frame",
    "start_frame_bleed",
    "extreme_blur",
    "cast_dropout",
    "hallucinated_character",
    "character_inconsistency",
    "skin_color_inconsistency",
    "costume_inconsistency",
    "spatial_axis_flip",
    "character_overlap",
    "object_materialized",
    "object_vanished",
    "duplicate_prop",
    "prop_part_missing",
    "self_moving_object",
    "prop_inverted",
    "rigid_body_deformation",
    "floating_object",
    "hallucinated_object",
    "wrong_support_surface",
}
_SEVERE_FLAG_PREFIXES = (
    "missing_character",
    "duplicate_character",
    "wrong_speaker",
    "prop_mismatch",
)


def _extract_severe_flags(flags: list[str]) -> set[str]:
    """Return all artifact flags that match exact severe flags or severe flag prefixes."""
    return {
        f
        for f in flags
        if f in _SEVERE_EXACT_FLAGS or f.startswith(_SEVERE_FLAG_PREFIXES)
    }


def _build_clip_qa_prompt(sview: ShotView, shot: Shot, attempt: int) -> str:
    """Build the Stage S9 VLM evaluation prompt for a rendered shot."""
    pos_map = {c.entity_id: c.position for c in shot.cast}
    cast_desc = [
        f"{ent.canonical_name} [position={pos_map.get(cid, 'center')}]: "
        f"{sview.cast_appearances[cid].visual_description} "
        f"(wardrobe: {sview.cast_appearances[cid].wardrobe})"
        for cid, ent in sview.cast_entities.items()
        if cid in sview.cast_appearances
    ]
    props_desc = [
        f"{sview.prop_entities[pid].canonical_name if pid in sview.prop_entities else pid} "
        f"[t=0.0s supported_by={sview.prop_states.get(pid, {}).get('supported_by', 'in scene')}; "
        f"state={sview.prop_states.get(pid, {}).get('pre_state', '')} -> {sview.prop_states.get(pid, {}).get('post_state', '')}]"
        for pid in shot.prop_ids
    ]
    beats_desc = [
        f"{b.description}"
        + (
            f" [{b.pre_state} -> {b.post_state}]"
            if b.pre_state and b.post_state
            else ""
        )
        for b in shot.beats
    ]
    return (
        f"Evaluate rendered clip for shot_id={shot.id} (attempt={attempt}).\n"
        f"StyleGuide: {sview.style_guide.visual_medium} (palette: {sview.style_guide.palette}).\n"
        f"Expected Cast Appearances & Blocking (judge ONLY against these S3 designs, NOT external assumptions): {cast_desc}.\n"
        f"Expected Props & Physical Support States: {props_desc}.\n"
        f"Expected location: {sview.location.canonical_name} ({sview.location_appearance.visual_description}).\n"
        f"Expected action beats: {beats_desc}.\n"
        "Verify every expected cast member is visible (flag 'missing_character_<id>' if absent or 'duplicate_character_<id>' if cloned) "
        "and their left/center/right order matches expected blocking (flag 'spatial_axis_flip' or 'character_overlap' if violated). "
        "Audit physical plausibility (`physics_plausibility`) and object permanence (`object_permanence`) across all timeline frames: "
        "flag 'start_frame_bleed' if Frame 0 shows a reference sheet, split-screen card, or static title card; "
        "flag 'object_materialized' if a table, character, or prop appears out of thin air mid-clip; "
        "flag 'object_vanished' if a held bowl/prop is dropped and disappears instead of being placed on a counter/table; "
        "flag 'duplicate_prop' if a pulled towel or held prop simultaneously remains hanging on its hook; "
        "flag 'prop_part_missing' or 'rigid_body_deformation' if a chair loses its backrest or warps; "
        "flag 'self_moving_object' if a chair or prop slides itself under a table without hand contact; "
        "and flag 'floating_object' or 'wrong_support_surface' if a prop hangs in mid-air. "
        "Set dialogue_wer = 0.0 (static frames do not include audio). "
        "Account for shallow depth-of-field bokeh on MCU/CU shots and multi-frame static sampling. "
        "Return all similarity/match scores strictly in the [0.0, 1.0] range."
    )


def _normalize_qa_report(
    raw_report: QAReport, cfg: Config, is_mock: bool
) -> tuple[QAReport, set[str]]:
    """Normalize raw VLM scores into `[0.0, 1.0]` and identify severe artifact flags."""
    _ = cfg
    w_score = _norm01(raw_report.wardrobe_match)
    s_score = _norm01(raw_report.setting_match)
    a_score = _norm01(raw_report.action_achieved)
    c_score = _norm01(raw_report.continuity_prev_shot)
    p_score = _norm01(raw_report.physics_plausibility)
    o_score = _norm01(raw_report.object_permanence)
    f_sims = {k: _norm01(val) for k, val in raw_report.face_similarity.items()}
    d_wer = _norm01(raw_report.dialogue_wer) if is_mock else 0.0
    severe_flags = _extract_severe_flags(raw_report.artifact_flags)
    normalized = raw_report.model_copy(
        update={
            "face_similarity": f_sims,
            "wardrobe_match": w_score,
            "setting_match": s_score,
            "action_achieved": a_score,
            "continuity_prev_shot": c_score,
            "physics_plausibility": p_score,
            "object_permanence": o_score,
            "dialogue_wer": d_wer,
        }
    )
    return normalized, severe_flags


def _collect_qa_failures(
    report: QAReport,
    cfg: Config,
    is_mock: bool,
    severe_flags: set[str],
    require_continuity: bool = False,
) -> list[str]:
    """Check normalized `report` metrics against `cfg.qa` thresholds and severe artifact flags."""
    reasons = list(report.failure_reasons) if (is_mock or severe_flags) else []
    for flag in sorted(severe_flags):
        flag_msg = f"Severe artifact flag: {flag}"
        if flag_msg not in reasons:
            reasons.append(flag_msg)
    for char_id, sim in report.face_similarity.items():
        if sim < cfg.qa.face_cosine_min:
            reasons.append(
                f"Face similarity for {char_id} ({sim:.2f}) < {cfg.qa.face_cosine_min}"
            )
    checks = [
        (
            report.wardrobe_match < cfg.qa.wardrobe_vlm_min,
            f"Wardrobe match ({report.wardrobe_match:.2f}) < {cfg.qa.wardrobe_vlm_min}",
        ),
        (
            report.setting_match < cfg.qa.setting_vlm_min,
            f"Setting match ({report.setting_match:.2f}) < {cfg.qa.setting_vlm_min}",
        ),
        (
            report.action_achieved < cfg.qa.action_vlm_min,
            f"Action score ({report.action_achieved:.2f}) < {cfg.qa.action_vlm_min}",
        ),
        (
            report.physics_plausibility < cfg.qa.physics_vlm_min,
            f"Physics plausibility ({report.physics_plausibility:.2f}) < {cfg.qa.physics_vlm_min}",
        ),
        (
            report.object_permanence < cfg.qa.permanence_vlm_min,
            f"Object permanence ({report.object_permanence:.2f}) < {cfg.qa.permanence_vlm_min}",
        ),
        (
            report.dialogue_wer > cfg.qa.dialogue_wer_max,
            f"Dialogue WER ({report.dialogue_wer:.2f}) > {cfg.qa.dialogue_wer_max}",
        ),
        (
            require_continuity and report.continuity_prev_shot < 0.60,
            f"Continuity with previous shot ({report.continuity_prev_shot:.2f}) < 0.60",
        ),
    ]
    for failed, msg in checks:
        if failed:
            reasons.append(msg)
    return reasons


def _register_last_frame(
    repo: Repo,
    cfg: Config,
    shot: Shot,
    run: GenerationRun,
    png_bytes: bytes,
    passed: bool = True,
) -> str:
    """Register the extracted last frame of `run` as APPROVED only when QA passed."""
    pipeline_ctx = ToolContext(repo=repo, role=Role.PIPELINE, cfg=cfg)
    lf_dict = wt.register_asset(
        pipeline_ctx,
        base_asset_id=f"ast_lastframe_{shot.id}",
        kind="first_frame",
        png_bytes=png_bytes,
        depicts_entity_ids=[c.entity_id for c in shot.cast],
        appearance_ids=[],
        generation_prompt=f"Extracted last frame of {shot.id} (run {run.id})",
        model="ffmpeg-frame-extractor",
        seed=run.seed,
        status=Status.APPROVED if passed else Status.PROPOSED,
    )
    return str(lf_dict["id"])


def evaluate_clip_qa(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    run: GenerationRun,
) -> QAReport:
    """Run Stage S9 multimodal clip QA on a rendered `GenerationRun`, recording `qa_scores` and last-frame Asset."""
    critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
    sview = shot_view(repo, shot.id)
    frames, ref_images = _load_clip_and_ref_images(repo, run)

    prompt = _build_clip_qa_prompt(sview, shot, run.attempt)
    raw_report = vlm.review(images=ref_images, prompt=prompt, schema=QAReport)
    is_mock = vlm.__class__.__name__ == "MockVLMProvider"
    if not is_mock:
        cv_flags = detect_frame_anomalies(frames)
        if cv_flags:
            merged_flags = list(dict.fromkeys([*raw_report.artifact_flags, *cv_flags]))
            raw_report = raw_report.model_copy(update={"artifact_flags": merged_flags})
    report, severe_flags = _normalize_qa_report(raw_report, cfg, is_mock)
    req_cont = bool(
        shot.continue_from_last_frame and sview.prev_shot_last_frame is not None
    )
    failure_reasons = _collect_qa_failures(
        report, cfg, is_mock, severe_flags, require_continuity=req_cont
    )

    passed = len(failure_reasons) == 0 and (report.passed or not is_mock)
    lf_id = _register_last_frame(repo, cfg, shot, run, frames[-1], passed=passed)
    suggested_fix = (
        "none"
        if passed
        else ("retry_seed" if report.suggested_fix == "none" else report.suggested_fix)
    )
    final_report = report.model_copy(
        update={
            "passed": passed,
            "failure_reasons": failure_reasons,
            "suggested_fix": suggested_fix,
        }
    )
    wt.record_clip_qa(
        critic_ctx,
        run_id=run.id,
        qa_report=final_report,
        extracted_last_frame_asset_id=lf_id,
    )
    return final_report

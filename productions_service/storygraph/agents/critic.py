"""CRITIC agent (`critic_agent`) for Stage S3 Visual Asset QA and Stage S9 Multimodal Clip QA.

S9 is spec-aware: the VLM sees the compiled OmniClipSpec, labelled REFERENCE images, the previous
approved clip's last frame and densely sampled timestamped frames, and returns a `ClipRubric`.
Approval is decided deterministically by `qa.critic.gate.gate` (any high defect blocks).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from ..adapters.base import VLMProvider
from ..adapters.media_frames import (
    ClipProbe,
    detect_frame_anomalies,
    extract_representative_frames_png,
    label_image,
    probe_clip,
)
from ..config import Config
from ..qa.critic.checks import CriticThresholds, MediaSignals, norm01
from ..qa.critic.gate import evaluate_rubric, gate
from ..qa.critic.legacy import (
    collect_qa_failures,
    extract_severe_flags,
    legacy_defects,
    normalize_qa_report,
)
from ..qa.critic.prompt import (
    PREV_FRAME_LABEL,
    build_critic_prompt,
    frame_label,
    reference_label,
)
from ..qa.critic.rubric import RUBRIC_VERSION, ClipRubric
from ..qa.critic.spec import CriticSpec, parse_compiled_spec
from ..repo import Repo
from ..schema import GenerationRun, QAReport, Role, Shot, Status
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import ShotView, shot_view

logger = logging.getLogger(__name__)

_extract_representative_frames_png = extract_representative_frames_png
# Back-compat aliases for callers/tests of the pre-rubric critic.
_normalize_qa_report = normalize_qa_report
_collect_qa_failures = collect_qa_failures
_extract_severe_flags = extract_severe_flags

_MAX_REFERENCE_IMAGES = 6
_PROMPT_PATH = Path(__file__).parent / "prompts" / "critic.md"


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


@lru_cache(maxsize=1)
def _critic_instructions() -> str:
    """System rubric text shared with the ADK critic role (`prompts/critic.md`)."""
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        return (
            "You are the clip QA critic. Fill every rubric verdict with observed facts."
        )


def _entity_names(sview: ShotView) -> dict[str, str]:
    """Entity id -> display name for cast, props and location."""
    names = {cid: e.canonical_name for cid, e in sview.cast_entities.items()}
    names.update({pid: e.canonical_name for pid, e in sview.prop_entities.items()})
    names[sview.location.id] = sview.location.canonical_name
    return names


def _reference_images(
    repo: Repo, run: GenerationRun, sview: ShotView
) -> list[tuple[str, bytes]]:
    """Labelled identity references (never mixed with clip frames; first frames excluded)."""
    names = _entity_names(sview)
    refs: list[tuple[str, bytes]] = []
    for aid in run.reference_asset_ids[:_MAX_REFERENCE_IMAGES]:
        asset = repo.get_asset(aid)
        raw = _safe_blob_bytes(repo, asset.uri) if asset else b""
        if not asset or not raw or asset.kind in ("first_frame", "audio"):
            continue
        who = " + ".join(names.get(e, e) for e in asset.depicts_entity_ids) or aid
        kind = "setting identity" if asset.kind == "location_plate" else "identity"
        refs.append((reference_label(who, kind), raw))
    return refs


def _assemble_images(
    refs: list[tuple[str, bytes]], prev_frame: bytes | None, probe: ClipProbe
) -> tuple[list[bytes], list[str]]:
    """Order: references, previous last frame, then timestamped clip frames (labels burned in)."""
    labelled = list(refs)
    if prev_frame:
        labelled.append((PREV_FRAME_LABEL, prev_frame))
    last_idx = len(probe.frames) - 1
    labelled += [
        (frame_label(f.t_s, i == last_idx), f.png) for i, f in enumerate(probe.frames)
    ]
    return [label_image(png, label) for label, png in labelled], [
        lbl for lbl, _ in labelled
    ]


def _media_signals(
    probe: ClipProbe, prev_frame: bytes | None, run_cv: bool
) -> MediaSignals:
    """Deterministic signals; pixel-anomaly flags only for real (non-mock) VLM reviews."""
    pngs = [f.png for f in probe.frames]
    cv_flags = (
        detect_frame_anomalies(pngs, prev_last_frame=prev_frame) if run_cv else []
    )
    return MediaSignals(
        duration_s=probe.duration_s,
        cut_times_s=probe.cut_times_s,
        voiced_ratio=probe.voiced_ratio,
        cv_flags=tuple(cv_flags),
        has_prev_frame=prev_frame is not None,
        frames_sampled=len(probe.frames),
    )


def _face_similarity(scores: dict[str, float], sview: ShotView) -> dict[str, float]:
    """Key identity scores by cast entity id where the subject name resolves."""
    by_name = {e.canonical_name.lower(): cid for cid, e in sview.cast_entities.items()}
    return {by_name.get(n.lower(), n): s for n, s in scores.items()}


def grade_rubric(
    spec: CriticSpec,
    rubric: ClipRubric,
    signals: MediaSignals,
    thr: CriticThresholds,
    sview: ShotView,
) -> QAReport:
    """Deterministically grade a VLM rubric into a gated `QAReport`."""
    outcome = evaluate_rubric(spec, rubric, signals, thr)
    decision = gate(outcome.defects, thr)
    return QAReport(
        face_similarity=_face_similarity(outcome.identity_scores, sview),
        identity_scores=outcome.identity_scores,
        wardrobe_match=norm01(rubric.wardrobe_match),
        setting_match=norm01(rubric.setting_match),
        physics_plausibility=norm01(rubric.physics_plausibility),
        dialogue_wer=0.0,
        artifact_flags=decision.artifact_flags,
        passed=decision.passed,
        failure_reasons=decision.failure_reasons,
        suggested_fix=decision.suggested_fix,
        defects=outcome.defects,
        steps_done=outcome.steps_done,
        hard_cut_times_s=outcome.cut_times_s,
        frames_sampled=signals.frames_sampled,
        rubric_version=RUBRIC_VERSION,
        **outcome.scores,
    )


def _grade_legacy(
    raw: QAReport, cfg: Config, is_mock: bool, signals: MediaSignals
) -> QAReport:
    """Grade a bare `QAReport` responder (no per-step verdicts) by floors + severe flags."""
    merged = list(dict.fromkeys([*raw.artifact_flags, *signals.cv_flags]))
    report, severe = normalize_qa_report(
        raw.model_copy(update={"artifact_flags": merged}), cfg, is_mock
    )
    reasons = collect_qa_failures(
        report, cfg, is_mock, severe, require_continuity=signals.has_prev_frame
    )
    passed = not reasons and (report.passed or not is_mock)
    fix = report.suggested_fix if report.suggested_fix != "none" else "retry_seed"
    return report.model_copy(
        update={
            "passed": passed,
            "failure_reasons": reasons,
            "suggested_fix": "none" if passed else fix,
            "defects": legacy_defects(reasons),
            "identity_scores": dict(report.face_similarity),
            "frames_sampled": signals.frames_sampled,
            "rubric_version": "legacy-qareport",
        }
    )


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


def _log_verdict(repo: Repo, shot: Shot, run: GenerationRun, report: QAReport) -> None:
    logger.info(
        "clip_qa_verdict",
        extra={
            "who": "storygraph.agents.critic",
            "where": "critic.evaluate_clip_qa",
            "what": "clip_qa_passed" if report.passed else "clip_qa_blocked",
            "when": datetime.now(UTC).isoformat(),
            "why": "; ".join(report.failure_reasons[:3]) or "no blocking defects",
            "how": f"{report.rubric_version} gate over {report.frames_sampled} frames",
            "project_id": repo.project_id,
            "shot_id": shot.id,
            "run_id": run.id,
            "attempt": run.attempt,
            "defect_causes": sorted({d.likely_cause for d in report.defects}),
        },
    )


def evaluate_clip_qa(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    run: GenerationRun,
) -> QAReport:
    """Run Stage S9 spec-aware clip QA on `run`, recording `qa_scores` and the last-frame Asset."""
    sview = shot_view(repo, shot.id)
    spec = parse_compiled_spec(run.compiled_prompt)
    probe = probe_clip(_safe_blob_bytes(repo, run.output_video_uri, b"mock_mp4"))
    prev = sview.prev_shot_last_frame
    prev_png = _safe_blob_bytes(repo, prev.uri) if prev else b""
    images, labels = _assemble_images(
        _reference_images(repo, run, sview), prev_png or None, probe
    )
    prompt = build_critic_prompt(
        shot.id, spec, labels, bool(prev_png), _critic_instructions()
    )
    raw = vlm.review(images=images, prompt=prompt, schema=ClipRubric)
    is_mock = vlm.__class__.__name__ == "MockVLMProvider"
    signals = _media_signals(probe, prev_png or None, run_cv=not is_mock)
    if isinstance(raw, QAReport):
        report = _grade_legacy(raw, cfg, is_mock, signals)
    else:
        thr = CriticThresholds.from_cfg(cfg.qa)
        report = grade_rubric(spec, raw, signals, thr, sview)
    lf_id = _register_last_frame(
        repo, cfg, shot, run, probe.last_frame_png, passed=report.passed
    )
    critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
    wt.record_clip_qa(
        critic_ctx, run_id=run.id, qa_report=report, extracted_last_frame_asset_id=lf_id
    )
    _log_verdict(repo, shot, run, report)
    return report

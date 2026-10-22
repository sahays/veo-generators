"""CRITIC agent (`critic_agent`) for Stage S3 Visual Asset QA and Stage S9 Multimodal Clip QA.

S9 is a thin gate over the reusable video-eval engine (`storygraph.eval`): one sectioned VLM call
(compiled OmniClipSpec, labelled REFERENCE images, previous last frame, dense timestamped
frames) plus shared deterministic metrics feed eleven named dimensions; `eval.gate.decide`
approves deterministically (any HIGH defect, >= 3 MEDIUM, a confident hard-gate dimension
below threshold, or the weighted overall below threshold blocks).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from ..adapters.base import VLMProvider
from ..adapters.embeddings import ImageEmbedder, make_embedder
from ..adapters.media_frames import extract_representative_frames_png
from ..adapters.transcribe import GeminiTranscriber
from ..config import Config
from ..eval.contracts import EvalInput, LabelledRef
from ..eval.engine import Collected, EvalEngine
from ..eval.gate import decide, gate_fingerprint
from ..eval.mapping import to_qa_report
from ..eval.media import media_signals
from ..eval.metrics.video import VideoMetrics
from ..eval.rubric import EvalRubric
from ..qa.critic.checks import CriticThresholds, MediaSignals
from ..qa.critic.legacy import (
    collect_qa_failures,
    extract_severe_flags,
    legacy_defects,
    normalize_qa_report,
)
from ..qa.critic.prompt import reference_label
from ..repo import Repo
from ..repo.prompt_versions import PromptVersionRepo
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
) -> list[LabelledRef]:
    """Labelled identity references (never mixed with clip frames; first frames excluded)."""
    names = _entity_names(sview)
    refs: list[LabelledRef] = []
    for aid in run.reference_asset_ids[:_MAX_REFERENCE_IMAGES]:
        asset = repo.get_asset(aid)
        raw = _safe_blob_bytes(repo, asset.uri) if asset else b""
        if not asset or not raw or asset.kind in ("first_frame", "audio"):
            continue
        who = [names.get(e, e) for e in asset.depicts_entity_ids]
        setting = asset.kind == "location_plate"
        label = reference_label(
            " + ".join(who) or aid, "setting identity" if setting else "identity"
        )
        kind: Literal["identity", "setting"] = "setting" if setting else "identity"
        refs.append(LabelledRef(label=label, kind=kind, entity_names=who, png=raw))
    return refs


def _face_ids(sview: ShotView) -> dict[str, str]:
    """Lower-cased subject display name -> cast entity id."""
    return {e.canonical_name.lower(): cid for cid, e in sview.cast_entities.items()}


@lru_cache(maxsize=1)
def _live_helpers() -> tuple[ImageEmbedder, GeminiTranscriber]:
    """Process-wide embedder + transcriber for real (non-mock) reviews (cached clients)."""
    return make_embedder(prefer_vertex=True), GeminiTranscriber()


def _engine(cfg: Config, vlm: VLMProvider, is_mock: bool) -> EvalEngine:
    """The shared eval engine; mock reviews skip network-backed metrics."""
    embedder, transcriber = (None, None) if is_mock else _live_helpers()
    return EvalEngine(
        vlm=vlm,
        gate_cfg=cfg.eval,
        thr=CriticThresholds.from_cfg(cfg.qa),
        embedder=embedder,
        transcriber=transcriber,
        instructions=_critic_instructions(),
        run_cv=not is_mock,
    )


def grade_eval(
    engine: EvalEngine,
    inp: EvalInput,
    got: Collected,
    rubric: EvalRubric,
    sview: ShotView,
) -> QAReport:
    """Grade a sectioned rubric through every eval dimension and the eval gate."""
    report = engine.grade(inp, got, rubric)
    decision, dims, _overall = decide(report.results, engine.gate_cfg, engine.thr)
    return to_qa_report(report, decision, dims, rubric, _face_ids(sview))


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


def _eval_input(
    repo: Repo, shot: Shot, run: GenerationRun, sview: ShotView
) -> EvalInput:
    prev = sview.prev_shot_last_frame
    prev_png = _safe_blob_bytes(repo, prev.uri) if prev else b""
    style = sview.style_guide.visual_medium if sview.style_guide else ""
    return EvalInput(
        clip_bytes=_safe_blob_bytes(repo, run.output_video_uri, b"mock_mp4"),
        spec_json=PromptVersionRepo(repo.store).spec_for_run(run),
        refs=_reference_images(repo, run, sview),
        prev_last_frame=prev_png or None,
        style_guide=style,
        shot_id=shot.id,
    )


def evaluate_clip_qa(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    run: GenerationRun,
) -> QAReport:
    """Run Stage S9 clip QA (video-eval engine), recording `qa_scores` and the last frame."""
    sview = shot_view(repo, shot.id)
    is_mock = vlm.__class__.__name__ == "MockVLMProvider"
    engine = _engine(cfg, vlm, is_mock)
    inp = _eval_input(repo, shot, run, sview)
    got = engine.collect(inp)
    if isinstance(got.raw, QAReport):
        signals = media_signals(
            got.probe, inp.prev_last_frame, VideoMetrics(), not is_mock
        )
        report = _grade_legacy(got.raw, cfg, is_mock, signals)
    else:
        report = grade_eval(engine, inp, got, got.raw, sview)
    report = report.model_copy(update={"gate_version": gate_fingerprint(cfg)})
    lf_id = _register_last_frame(
        repo, cfg, shot, run, got.probe.last_frame_png, passed=report.passed
    )
    critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
    wt.record_clip_qa(
        critic_ctx, run_id=run.id, qa_report=report, extracted_last_frame_asset_id=lf_id
    )
    _log_verdict(repo, shot, run, report)
    return report

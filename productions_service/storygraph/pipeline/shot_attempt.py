"""One render+QA attempt for a shot: compile, generate, store the clip, run the critic.

Split from `render_stage` so both the S8 retry loop and the QA repair loop share it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..adapters.base import VideoGenerator, VLMProvider
from ..adapters.clip_trim import TrimResult, trim_late_hard_cut
from ..adapters.media_frames import trim_leading_reference_or_static_frames
from ..adapters.omni.package import build_ref_labels, to_render_package
from ..agents.critic import evaluate_clip_qa
from ..budget import RefPlan, select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..qa.llm_rewrite import make_llm_rewriter
from ..qa.retry_rewrite import ReasonRewriter, context_from_view, rewrite_retry_feedback
from ..repair.models import RepairDirective
from ..repo import Repo
from ..schema import ClipTrim, GenerationRun, Role, Shot, Status
from ..shots import run_matches_shot
from ..views import ShotView, shot_view
from .prompt_versioning import record_run_result, resolve_package

logger = logging.getLogger(__name__)

_NO_COMPOSITE_FLAGS: frozenset[str] = frozenset(
    {
        "start_frame_bleed",
        "prop_morphing",
        "character_morphing",
        "duplicate_prop",
        "duplicate_character",
    }
)


@dataclass
class RenderDeps:
    """Adapters and shared state every render attempt needs."""

    repo: Repo
    cfg: Config
    video_gen: VideoGenerator
    vlm: VLMProvider
    packages: dict[str, Package] = field(default_factory=dict)


def resolve_target_resolution(repo: Repo) -> str:
    """Return '720p' when project render_quality is 'final', otherwise '360p' (draft default)."""
    meta = repo.get_project_meta()
    if meta and (meta.render_quality == "final" or meta.video_resolution == "720p"):
        return "720p"
    return "360p"


def _load_conditioning_bytes(repo: Repo, pkg: Package) -> list[bytes]:
    """Load reference and first-frame image bytes used to condition a video render package."""
    out: list[bytes] = []
    for uri in [
        *pkg.reference_uris,
        *([pkg.first_frame_uri] if pkg.first_frame_uri else []),
    ]:
        try:
            out.append(repo.blobs.get_bytes(uri))
        except Exception as exc:  # noqa: BLE001 - blob backends raise untyped errors
            logger.info(
                "Conditioning image unreadable; excluded from start-frame trim",
                extra={
                    "who": "storygraph.pipeline.shot_attempt",
                    "where": "shot_attempt._load_conditioning_bytes",
                    "what": "conditioning_image_skipped",
                    "when": datetime.now(UTC).isoformat(),
                    "why": str(exc),
                    "how": "repo.blobs.get_bytes",
                    "shot_id": pkg.shot_id,
                    "uri": uri,
                },
            )
    return out


def _pop_fallback(video_gen: VideoGenerator, shot_id: str) -> dict[str, Any] | None:
    """Fetch the adapter's fallback record for the render that just finished, if any."""
    pop = getattr(video_gen, "pop_fallback", None)
    record = pop(shot_id) if callable(pop) else None
    return record.to_dict() if record is not None else None


def _attach_fallback(
    repo: Repo, run_node: GenerationRun, fallback: dict[str, Any] | None
) -> GenerationRun:
    """Log the render fallback and persist it on the run."""
    if not fallback:
        return run_node
    logger.warning(
        "Clip rendered via fallback level %s",
        fallback.get("fallback_level"),
        extra={
            "who": "storygraph.pipeline.shot_attempt",
            "where": "shot_attempt._attach_fallback",
            "what": "render_fallback_recorded",
            "when": datetime.now(UTC).isoformat(),
            "why": "; ".join(fallback.get("reasons", [])),
            "how": "GeminiVideoGenerator.pop_fallback",
            "project_id": repo.project_id,
            "shot_id": run_node.shot_id,
            "run_id": run_node.id,
            "fallback_level": fallback.get("fallback_level"),
            "refs_dropped": fallback.get("refs_dropped", []),
        },
    )
    return run_node.model_copy(update={"render_fallback": fallback})


def _trim_late_cut(repo: Repo, shot_id: str, clip_bytes: bytes) -> TrimResult:
    """Cut the tail after a late hard cut (>= 75% of duration) and log the decision."""
    result = trim_late_hard_cut(clip_bytes)
    if result.trimmed:
        logger.info(
            "Late hard cut trimmed before QA",
            extra={
                "who": "storygraph.pipeline.shot_attempt",
                "where": "shot_attempt._trim_late_cut",
                "what": "late_hard_cut_trimmed",
                "when": datetime.now(UTC).isoformat(),
                "why": f"scene cut at t={result.cut_at_s:.2f}s in late window",
                "how": "ffmpeg scene detect + re-encode with -t (A/V synced)",
                "project_id": repo.project_id,
                "shot_id": shot_id,
                "original_duration_s": result.original_duration_s,
                "duration_s": result.duration_s,
            },
        )
    return result


def _clip_trim_record(result: TrimResult) -> ClipTrim | None:
    if not result.trimmed:
        return None
    return ClipTrim(
        original_duration_s=result.original_duration_s,
        duration_s=result.duration_s,
        cut_at_s=result.cut_at_s,
    )


def _store_rendered_clip(
    repo: Repo,
    cfg: Config,
    shot_id: str,
    attempt: int,
    pkg: Package,
    clip_bytes: bytes,
    fallback: dict[str, Any] | None = None,
    shot_content_hash: str | None = None,
    prompt_version_id: str | None = None,
) -> GenerationRun:
    """Persist rendered video bytes (head bleed + late hard cut trimmed) and record GenerationRun."""
    has_cond = bool(pkg.reference_uris or pkg.first_frame_uri)
    cond_bytes = _load_conditioning_bytes(repo, pkg) if has_cond else []
    cleaned_bytes = trim_leading_reference_or_static_frames(
        clip_bytes, ref_frames=cond_bytes, has_conditioning_image=has_cond
    )
    trim = _trim_late_cut(repo, shot_id, cleaned_bytes)
    clip_uri = repo.blobs.put_bytes(
        f"clips/{shot_id}_att{attempt}_{pkg.package_hash[:8]}.mp4",
        trim.clip_bytes,
        content_type="video/mp4",
    )
    signed_clip = (
        repo.blobs.sign_url(clip_uri) if hasattr(repo.blobs, "sign_url") else clip_uri
    )
    run_node = GenerationRun(
        id=f"run_{shot_id}_att{attempt}_{uuid.uuid4().hex[:6]}",
        created_by=Role.PIPELINE,
        status=Status.RENDERED,
        shot_id=shot_id,
        attempt=attempt,
        provider=cfg.video.provider,
        model=cfg.video.model,
        compiled_prompt=pkg.compiled_prompt,
        negative_prompt=pkg.negative_prompt,
        reference_asset_ids=pkg.reference_asset_ids,
        first_frame_asset_id=pkg.first_frame_asset_id,
        seed=pkg.seed,
        package_hash=pkg.package_hash,
        output_video_uri=clip_uri,
        output_video_signed_url=signed_clip,
        shot_content_hash=shot_content_hash,
        clip_trim=_clip_trim_record(trim),
        prompt_version_id=prompt_version_id,
        spec_json=pkg.spec_source,
        prompt_format=pkg.prompt_format if pkg.spec_json else "json",
    )
    run_node = _attach_fallback(repo, run_node, fallback)
    repo.add_generation_run(run_node)
    return run_node


def latest_current_run(repo: Repo, shot: Shot) -> GenerationRun | None:
    """Latest GenerationRun rendered from the shot's current content, if any."""
    runs = [
        r
        for r in repo.list_generation_runs(shot_id=shot.id)
        if run_matches_shot(r, shot)
    ]
    return runs[-1] if runs else None


def _collect_retry_context(
    repo: Repo, view: ShotView, llm: ReasonRewriter | None = None
) -> tuple[list[str], bool]:
    """Return `(retry targets, allow_composites)` from the shot's previous run of its current content."""
    last = latest_current_run(repo, view.shot)
    if last is None or last.qa_scores is None:
        return [], True
    sc = last.qa_scores
    feedback = rewrite_retry_feedback(sc, context_from_view(view), llm)
    allow_comp = not bool(
        _NO_COMPOSITE_FLAGS & set(sc.artifact_flags)
        or any("duplicate_character" in f for f in sc.artifact_flags)
    )
    return feedback, allow_comp


def _with_render_context(
    repo: Repo, view: ShotView, plan: RefPlan, pkg: Package
) -> Package:
    """Attach reference identity labels and project safety context for the video adapter."""
    meta = repo.get_project_meta()
    return to_render_package(
        pkg,
        build_ref_labels(view, plan.selected_assets),
        project_id=repo.project_id,
        visual_style_preset=view.style_guide.visual_style_preset
        or (meta.visual_style_preset if meta else ""),
        language=meta.language if meta else "",
    )


def _retry_inputs(
    deps: RenderDeps, sv: ShotView, attempt: int, repair: RepairDirective | None
) -> tuple[list[str], bool]:
    """Retry targets + composite permission: from the directive on repairs, else from QA."""
    if repair is not None:
        return [], repair.allow_composites
    if attempt <= 1:
        return [], True
    llm = make_llm_rewriter(deps.vlm) if deps.cfg.qa.retry_rewrite_llm else None
    return _collect_retry_context(deps.repo, sv, llm)


def _build_package(
    deps: RenderDeps,
    sv: ShotView,
    attempt: int,
    repair: RepairDirective | None,
) -> Package:
    retry_fb, allow_comp = _retry_inputs(deps, sv, attempt, repair)
    caps = deps.video_gen.caps
    plan = select_references(
        sv,
        deps.cfg,
        caps=caps,
        repo=deps.repo,
        allow_composites=allow_comp,
        repair=repair,
    )
    pkg = compile_shot(
        sv,
        plan,
        deps.cfg,
        caps=caps,
        project_id=deps.repo.project_id,
        attempt=attempt,
        retry_feedback=retry_fb or None,
        resolution=resolve_target_resolution(deps.repo),
        repair=repair,
    )
    return _with_render_context(deps.repo, sv, plan, pkg)


def render_attempt(
    deps: RenderDeps,
    shot: Shot,
    attempt: int,
    drop_last_frame: bool,
    repair: RepairDirective | None = None,
) -> bool:
    """Compile, generate video, and run VLM Critic QA for a single shot attempt."""
    repo = deps.repo
    sv = shot_view(repo, shot.id)
    if drop_last_frame:
        sv = sv.model_copy(update={"prev_shot_last_frame": None})
    reason = "repair" if repair is not None else f"attempt {attempt}"
    compiled = _build_package(deps, sv, attempt, repair)
    versioned = resolve_package(repo, sv.shot, compiled, reason)
    pkg = versioned.package
    deps.packages[shot.id] = pkg
    clip_bytes = deps.video_gen.generate(pkg)
    fallback = _pop_fallback(deps.video_gen, shot.id)
    run_node = _store_rendered_clip(
        repo,
        deps.cfg,
        shot.id,
        attempt,
        pkg,
        clip_bytes,
        fallback,
        sv.shot.content_hash,
        versioned.version.id,
    )
    qa_report = evaluate_clip_qa(repo, deps.cfg, deps.vlm, shot, run_node)
    record_run_result(repo, run_node, qa_report)
    if qa_report.passed:
        current = repo.get_shot(shot.id) or shot
        if current.stale:
            repo.put_shot(
                current.model_copy(update={"stale": False, "stale_reason": None})
            )
    return qa_report.passed


def next_attempt_number(repo: Repo, shot_id: str) -> int:
    """Monotonic attempt number (also the seed salt) for the shot's next render."""
    return len(repo.list_generation_runs(shot_id=shot_id)) + 1

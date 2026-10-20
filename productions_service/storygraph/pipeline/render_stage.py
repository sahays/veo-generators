"""Shot compilation, video rendering, QA retry loop, and scene-parallel execution for StoryGraph."""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from ..adapters.base import VideoGenerator, VLMProvider
from ..adapters.media_frames import trim_leading_reference_or_static_frames
from ..adapters.omni.package import build_ref_labels, to_render_package
from ..agents.critic import evaluate_clip_qa
from ..budget import RefPlan, select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..qa.llm_rewrite import make_llm_rewriter
from ..qa.retry_rewrite import ReasonRewriter, context_from_view, rewrite_retry_feedback
from ..repo import Repo
from ..schema import GenerationRun, Role, Shot, Status
from ..shots import run_matches_shot
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import ShotView, shot_view

logger = logging.getLogger(__name__)


def _resolve_target_resolution(repo: Repo) -> str:
    """Return '720p' when project render_quality is 'final', otherwise '360p' (draft default)."""
    meta = repo.get_project_meta()
    if meta and (meta.render_quality == "final" or meta.video_resolution == "720p"):
        return "720p"
    return "360p"


def compile_all_shots(
    repo: Repo, cfg: Config, video_gen: VideoGenerator
) -> dict[str, Package]:
    """Deterministically compile all shots in the repository into render packages."""
    compiled: dict[str, Package] = {}
    resolution = _resolve_target_resolution(repo)
    for shot in repo.list_shots():
        sv = shot_view(repo, shot.id)
        plan = select_references(sv, cfg, caps=video_gen.caps, repo=repo)
        compiled[shot.id] = compile_shot(
            sv,
            plan,
            cfg,
            caps=video_gen.caps,
            project_id=repo.project_id,
            attempt=1,
            resolution=resolution,
        )
    return compiled


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
                    "who": "storygraph.pipeline.render_stage",
                    "where": "render_stage._load_conditioning_bytes",
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
            "who": "storygraph.pipeline.render_stage",
            "where": "render_stage._attach_fallback",
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


def _store_rendered_clip(
    repo: Repo,
    cfg: Config,
    shot_id: str,
    attempt: int,
    pkg: Package,
    clip_bytes: bytes,
    fallback: dict[str, Any] | None = None,
    shot_content_hash: str | None = None,
) -> GenerationRun:
    """Persist rendered video bytes (after stripping any leading start-frame bleed) and record GenerationRun."""
    has_cond = bool(pkg.reference_uris or pkg.first_frame_uri)
    cond_bytes = _load_conditioning_bytes(repo, pkg) if has_cond else []
    cleaned_bytes = trim_leading_reference_or_static_frames(
        clip_bytes, ref_frames=cond_bytes, has_conditioning_image=has_cond
    )
    clip_uri = repo.blobs.put_bytes(
        f"clips/{shot_id}_att{attempt}_{pkg.package_hash[:8]}.mp4",
        cleaned_bytes,
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
    )
    run_node = _attach_fallback(repo, run_node, fallback)
    repo.add_generation_run(run_node)
    return run_node


def _collect_retry_context(
    repo: Repo, view: ShotView, llm: ReasonRewriter | None = None
) -> tuple[list[str], bool]:
    """Return `(retry targets, allow_composites)` from the shot's previous run of its current content."""
    runs = [
        r
        for r in repo.list_generation_runs(shot_id=view.shot.id)
        if run_matches_shot(r, view.shot)
    ]
    if not runs or runs[-1].qa_scores is None:
        return [], True
    sc = runs[-1].qa_scores
    feedback = rewrite_retry_feedback(sc, context_from_view(view), llm)
    no_comp_flags = {
        "start_frame_bleed",
        "prop_morphing",
        "character_morphing",
        "duplicate_prop",
        "duplicate_character",
    }
    allow_comp = not bool(
        no_comp_flags & set(sc.artifact_flags)
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


def attempt_shot_render(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
    shot: Shot,
    attempt: int,
    drop_last_frame: bool,
) -> bool:
    """Compile, generate video, and run VLM Critic QA for a single shot attempt."""
    sv = shot_view(repo, shot.id)
    if drop_last_frame:
        sv = sv.model_copy(update={"prev_shot_last_frame": None})
    llm = make_llm_rewriter(vlm) if cfg.qa.retry_rewrite_llm else None
    retry_fb, allow_comp = (
        _collect_retry_context(repo, sv, llm) if attempt > 1 else ([], True)
    )
    plan = select_references(
        sv,
        cfg,
        caps=video_gen.caps,
        repo=repo,
        allow_composites=allow_comp,
    )
    pkg = compile_shot(
        sv,
        plan,
        cfg,
        caps=video_gen.caps,
        project_id=repo.project_id,
        attempt=attempt,
        retry_feedback=retry_fb or None,
        resolution=_resolve_target_resolution(repo),
    )
    pkg = _with_render_context(repo, sv, plan, pkg)
    compiled_packages[shot.id] = pkg
    clip_bytes = video_gen.generate(pkg)
    fallback = _pop_fallback(video_gen, shot.id)
    run_node = _store_rendered_clip(
        repo, cfg, shot.id, attempt, pkg, clip_bytes, fallback, sv.shot.content_hash
    )
    qa_report = evaluate_clip_qa(repo, cfg, vlm, shot, run_node)
    if qa_report.passed and shot.stale:
        repo.put_shot(shot.model_copy(update={"stale": False, "stale_reason": None}))
    return qa_report.passed


_SEVERE_RENDER_FLAGS: frozenset[str] = frozenset(
    {
        "style_drift",
        "frozen_frame",
        "start_frame_bleed",
        "object_materialized",
        "duplicate_prop",
        "prop_part_missing",
        "self_moving_object",
        "prop_inverted",
        "floating_object",
        "teleportation",
        "missing_character",
    }
)


def _is_shot_already_valid(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    existing_runs: list[GenerationRun],
) -> bool:
    """Return True if the shot already has a clean approved run passing critical physics & permanence QA.

    Only runs rendered from the shot's current content (`run_matches_shot`) count.
    """
    current_runs = [r for r in existing_runs if run_matches_shot(r, shot)]
    if shot.stale or not current_runs:
        return False
    last_run = current_runs[-1]
    scores = last_run.qa_scores
    if scores is not None:
        if _SEVERE_RENDER_FLAGS & set(scores.artifact_flags):
            return False
        if (
            scores.physics_plausibility < cfg.qa.physics_vlm_min
            or scores.object_permanence < cfg.qa.permanence_vlm_min
        ):
            return False
    if last_run.status == Status.APPROVED:
        return True
    if not last_run.output_video_uri or cfg.video.provider == "mock":
        return False
    return evaluate_clip_qa(repo, cfg, vlm, shot, last_run).passed


def _should_drop_last_frame(repo: Repo, shot_id: str) -> bool:
    """Return True only when the latest failed run exhibited first-frame corruption or freeze."""
    runs = repo.list_generation_runs(shot_id=shot_id)
    if not runs or runs[-1].status != Status.FAILED or not runs[-1].qa_scores:
        return False
    flags = set(runs[-1].qa_scores.artifact_flags)
    return bool({"frozen_frame", "corrupted_first_frame"} & flags)


def render_single_shot_with_qa(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
    shot: Shot,
    max_retries: int,
) -> None:
    """Render a shot with bounded retries and file a Critic ChangeRequest if all attempts fail."""
    existing_runs = repo.list_generation_runs(shot_id=shot.id)
    if _is_shot_already_valid(repo, cfg, vlm, shot, existing_runs):
        return
    start_attempt = len(existing_runs) + 1
    passed = False
    for offset in range(max_retries):
        drop_lf = _should_drop_last_frame(repo, shot.id)
        if attempt_shot_render(
            repo,
            cfg,
            video_gen,
            vlm,
            compiled_packages,
            shot,
            start_attempt + offset,
            drop_lf,
        ):
            passed = True
            break
    if not passed:
        critic_ctx = ToolContext(repo=repo, role=Role.CRITIC, cfg=cfg)
        wt.create_change_request(
            critic_ctx,
            to_role=Role.DIRECTOR,
            target_node_id=shot.id,
            reason=f"Shot '{shot.id}' failed QA after {max_retries} attempt(s); suggested fix: resplit_shot",
            proposed_patch={"action": "resplit_shot"},
        )


def render_and_qa_shots(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
) -> None:
    """Render dirty/unrendered shots in story_order, parallelizing independent scene chains."""
    shots = sorted(
        repo.list_shots(),
        key=lambda s: (s.story_order, s.scene_id, s.index_in_scene),
    )
    max_retries = max(1, cfg.caps.shot_max_retries)
    if cfg.video.provider == "mock" or len(shots) <= 1:
        for shot in shots:
            render_single_shot_with_qa(
                repo, cfg, video_gen, vlm, compiled_packages, shot, max_retries
            )
        return
    scene_groups: dict[str, list[Shot]] = {}
    for shot in shots:
        scene_groups.setdefault(shot.scene_id, []).append(shot)
    _run_parallel_scene_groups(
        repo, cfg, video_gen, vlm, compiled_packages, scene_groups, max_retries
    )


def _run_parallel_scene_groups(
    repo: Repo,
    cfg: Config,
    video_gen: VideoGenerator,
    vlm: VLMProvider,
    compiled_packages: dict[str, Package],
    scene_groups: dict[str, list[Shot]],
    max_retries: int,
) -> None:
    """Execute each scene's sequential shot chain across a bounded thread pool."""

    def _run_scene_chain(scene_shots: list[Shot]) -> None:
        for sh in scene_shots:
            render_single_shot_with_qa(
                repo, cfg, video_gen, vlm, compiled_packages, sh, max_retries
            )

    with ThreadPoolExecutor(max_workers=min(4, len(scene_groups))) as pool:
        futs = [pool.submit(_run_scene_chain, grp) for grp in scene_groups.values()]
        for fut in futs:
            fut.result()


def evaluate_missing_qa(repo: Repo, cfg: Config, vlm: VLMProvider) -> None:
    """Run VLM Critic QA on any shot whose latest GenerationRun lacks qa_scores or physics verification."""
    for shot in repo.list_shots():
        runs = repo.list_generation_runs(shot_id=shot.id)
        if runs and runs[-1].qa_scores is None:
            evaluate_clip_qa(repo, cfg, vlm, shot, runs[-1])

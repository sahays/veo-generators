"""Shot compilation, video rendering, QA retry loop, and scene-parallel execution for StoryGraph."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from ..adapters.base import VideoGenerator, VLMProvider
from ..agents.critic import evaluate_clip_qa
from ..budget import select_references
from ..compile import Package, compile_shot
from ..config import Config
from ..repo import Repo
from ..schema import GenerationRun, Role, Shot, Status
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import shot_view


def compile_all_shots(
    repo: Repo, cfg: Config, video_gen: VideoGenerator
) -> dict[str, Package]:
    """Deterministically compile all shots in the repository into render packages."""
    compiled: dict[str, Package] = {}
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
        )
    return compiled


def _store_rendered_clip(
    repo: Repo, cfg: Config, shot_id: str, attempt: int, pkg: Package, clip_bytes: bytes
) -> GenerationRun:
    """Persist rendered video bytes to blob store and record the GenerationRun node."""
    clip_uri = repo.blobs.put_bytes(
        f"clips/{shot_id}_att{attempt}_{pkg.package_hash[:8]}.mp4",
        clip_bytes,
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
    )
    repo.add_generation_run(run_node)
    return run_node


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
    plan = select_references(sv, cfg, caps=video_gen.caps, repo=repo)
    pkg = compile_shot(
        sv,
        plan,
        cfg,
        caps=video_gen.caps,
        project_id=repo.project_id,
        attempt=attempt,
    )
    compiled_packages[shot.id] = pkg
    clip_bytes = video_gen.generate(pkg)
    run_node = _store_rendered_clip(repo, cfg, shot.id, attempt, pkg, clip_bytes)
    qa_report = evaluate_clip_qa(repo, cfg, vlm, shot, run_node)
    if qa_report.passed and shot.stale:
        repo.put_shot(shot.model_copy(update={"stale": False, "stale_reason": None}))
    return qa_report.passed


def _is_shot_already_valid(
    repo: Repo,
    cfg: Config,
    vlm: VLMProvider,
    shot: Shot,
    existing_runs: list[GenerationRun],
) -> bool:
    """Return True if the shot already has a clean approved run and is not stale."""
    if shot.stale or not existing_runs:
        return False
    last_run = existing_runs[-1]
    if last_run.status == Status.APPROVED:
        return True
    if not last_run.output_video_uri or cfg.video.provider == "mock":
        return False
    flags = set(last_run.qa_scores.artifact_flags) if last_run.qa_scores else set()
    if {"style_drift", "frozen_frame"} & flags:
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
    """Run VLM Critic QA on any shot whose latest GenerationRun lacks qa_scores."""
    for shot in repo.list_shots():
        runs = repo.list_generation_runs(shot_id=shot.id)
        if runs and runs[-1].qa_scores is None:
            evaluate_clip_qa(repo, cfg, vlm, shot, runs[-1])

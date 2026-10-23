"""Pipeline adapter for S8_KEYFRAMES: builds the renderer from pipeline providers and runs it."""

from __future__ import annotations

from dataclasses import dataclass

from ...adapters.base import ImageGenerator, VLMProvider
from ...config import Config
from ...keyframes.plate.build import PlateBuilder
from ...keyframes.render.renderer import KeyframeRenderer, RendererCfg
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.stage import (
    KeyframeStageDeps,
    KeyframeStageResult,
    run_keyframe_stage,
)
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo

# Rough Vertex list price per generated/edited image (budget accounting only).
USD_PER_KEYFRAME = 0.04
MAX_LISTED_FAILURES = 3


@dataclass(frozen=True)
class KeyframeStageOutcome:
    """What the StageRun records: estimated cost and, when shots failed, a readable error."""

    cost_usd: float
    error: str | None


def keyframe_deps(
    repo: Repo, cfg: Config, image_gen: ImageGenerator, vlm: VLMProvider
) -> KeyframeStageDeps:
    sink, aspect = RepoKeyframeSink(repo), _aspect(repo)
    retries = cfg.keyframes.max_retries
    renderer = KeyframeRenderer(
        image_gen,
        vlm,
        sink,
        repo.blobs.get_bytes,
        RendererCfg(model=cfg.image.model, aspect_ratio=aspect, max_retries=retries),
    )
    plates = PlateBuilder(image_gen, vlm, repo.blobs.get_bytes, aspect)
    return KeyframeStageDeps(
        repo=repo,
        renderer=renderer,
        plates=sink,
        plate_builder=plates,
        plate_model=cfg.image.model,
        max_retries=retries,
        scene_workers=cfg.keyframes.scene_workers,
    )


def _aspect(repo: Repo) -> str:
    meta = repo.get_project_meta()
    return meta.orientation if meta else "16:9"


def failure_summary(result: KeyframeStageResult) -> str | None:
    """StageRun error / UI banner text when some shots failed (None when all settled)."""
    if not result.failed:
        return None
    total = len(result.settled)
    listed = "; ".join(
        f"{sid}: {why}"
        for sid, why in sorted(result.failed.items())[:MAX_LISTED_FAILURES]
    )
    more = len(result.failed) - MAX_LISTED_FAILURES
    tail = f"; +{more} more" if more > 0 else ""
    return (
        f"S8_KEYFRAMES: {len(result.failed)} of {total} clips failed ({listed}{tail}). "
        "Resume keyframes re-derives only the failed/missing clips."
    )


def run_keyframes_stage(
    repo: Repo, cfg: Config, image_gen: ImageGenerator, vlm: VLMProvider
) -> KeyframeStageOutcome:
    """Run S8_KEYFRAMES; returns the estimated image cost (USD) and failure summary."""
    result = run_keyframe_stage(keyframe_deps(repo, cfg, image_gen, vlm))
    rendered = set(result.rendered)
    active = KeyframeSetRepo(repo.store).active_by_shot()
    images = sum(
        f.attempts for sid, ks in active.items() if sid in rendered for f in ks.frames
    )
    cost = round(images * USD_PER_KEYFRAME, 2)
    return KeyframeStageOutcome(cost, failure_summary(result))


def reset_keyframes(repo: Repo) -> int:
    """Supersede every active keyframe set (forced S8_KEYFRAMES re-derives all shots)."""
    return KeyframeSetRepo(repo.store).supersede_all()

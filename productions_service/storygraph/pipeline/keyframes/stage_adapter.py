"""Pipeline adapter for S8_KEYFRAMES: builds the renderer from pipeline providers and runs it."""

from __future__ import annotations

from ...adapters.base import ImageGenerator, VLMProvider
from ...config import Config
from ...keyframes.plate.build import PlateBuilder
from ...keyframes.render.renderer import KeyframeRenderer, RendererCfg
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.stage import KeyframeStageDeps, run_keyframe_stage
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo

# Rough Vertex list price per generated/edited image (budget accounting only).
USD_PER_KEYFRAME = 0.04


def keyframe_deps(
    repo: Repo, cfg: Config, image_gen: ImageGenerator, vlm: VLMProvider
) -> KeyframeStageDeps:
    sink, aspect = RepoKeyframeSink(repo), _aspect(repo)
    renderer = KeyframeRenderer(
        image_gen,
        vlm,
        sink,
        repo.blobs.get_bytes,
        RendererCfg(model=cfg.image.model, aspect_ratio=aspect),
    )
    plates = PlateBuilder(image_gen, vlm, repo.blobs.get_bytes, aspect)
    return KeyframeStageDeps(
        repo=repo,
        renderer=renderer,
        plates=sink,
        plate_builder=plates,
        plate_model=cfg.image.model,
    )


def _aspect(repo: Repo) -> str:
    meta = repo.get_project_meta()
    return meta.orientation if meta else "16:9"


def run_keyframes_stage(
    repo: Repo, cfg: Config, image_gen: ImageGenerator, vlm: VLMProvider
) -> float:
    """Run S8_KEYFRAMES; returns the estimated image cost (USD) for the StageRun."""
    result = run_keyframe_stage(keyframe_deps(repo, cfg, image_gen, vlm))
    rendered = set(result.rendered)
    active = KeyframeSetRepo(repo.store).active_by_shot()
    images = sum(
        f.attempts for sid, ks in active.items() if sid in rendered for f in ks.frames
    )
    return round(images * USD_PER_KEYFRAME, 2)


def reset_keyframes(repo: Repo) -> int:
    """Supersede every active keyframe set (forced S8_KEYFRAMES re-derives all shots)."""
    return KeyframeSetRepo(repo.store).supersede_all()

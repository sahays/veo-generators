"""Wire S8_PREVIZ dependencies from pipeline adapters (the only place that picks concretes)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..adapters.base import ImageGenerator, VideoGenerator, VLMProvider
from ..config import Config
from ..repo import Repo
from ..schema import Scene
from ..schemas.previz import PrevizLayout
from .layout import layout_for_scene
from .layout.estimate import LayoutEstimator
from .render.runner import BlenderRunner
from .scene import PrevizSceneBuilder
from .stage.deps import PrevizStageDeps
from .variants.context import VariantDeps


def blender_version() -> str | None:
    return BlenderRunner().version()


def raw_video_generator(video_gen: VideoGenerator) -> VideoGenerator:
    """The provider generator under any render-strategy wrapper (variants bind media)."""
    inner = getattr(video_gen, "inner", None)
    return inner if inner is not None else video_gen


def _aspect(repo: Repo) -> str:
    meta = repo.get_project_meta()
    return meta.orientation if meta and meta.orientation in ("16:9", "9:16") else "16:9"


def build_previz_deps(
    repo: Repo,
    cfg: Config,
    image_gen: ImageGenerator,
    vlm: VLMProvider,
    video_gen: VideoGenerator,
    workdir: Path | None = None,
) -> PrevizStageDeps:
    estimator = LayoutEstimator(vlm, repo.blobs.get_bytes)

    def layouts(scene: Scene) -> PrevizLayout:
        return layout_for_scene(repo, estimator, scene, _aspect(repo))

    meta = repo.get_project_meta()
    variants = VariantDeps(
        repo=repo,
        cfg=cfg,
        video_gen=raw_video_generator(video_gen),
        image_gen=image_gen,
        vlm=vlm,
        put=repo.blobs.put_bytes,
        style=(meta.visual_style_preset if meta else "") or "",
        image_model=cfg.image.model,
    )
    root = workdir or Path(os.getenv("PREVIZ_WORKDIR", tempfile.gettempdir()))
    root.mkdir(parents=True, exist_ok=True)
    return PrevizStageDeps(
        repo=repo,
        renderer=BlenderRunner(),
        layouts=layouts,
        build_scene=PrevizSceneBuilder(repo, _aspect(repo)),
        workdir=root,
        variants=variants,
    )

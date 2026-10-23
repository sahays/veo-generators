"""CLI: `python -m storygraph.experiments.keyframe_ab --stage keyframes|render|judge|report`.

Renders one scene of an exported production with three strategies (A direct hybrid,
B keyframe_interp, C animatic_edit), judges the clips and writes the report. Keyframes and
animatics are stored under `gs://<bucket>/kf_experiments/<project>/` (never production).
"""

from __future__ import annotations

import argparse
import logging
import os
from functools import cache
from pathlib import Path

from google.cloud import storage

from ...adapters.gemini_image import GeminiImageGenerator
from ...adapters.gemini_video import GeminiVideoGenerator
from ...adapters.vlm import GeminiVLMProvider
from ...config import VideoProviderCfg
from ...keyframes.animate.generator import KeyframeVideoGenerator
from ...keyframes.animate.sources import RenderingSource
from ...keyframes.plate.build import PlateBuilder
from ...keyframes.render.renderer import KeyframeRenderer, RendererCfg, ScenePlate
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.stage import KeyframeStageDeps, scene_context
from ...repo import Repo
from ...store import GcsBlobStore
from .contracts import VariantId
from .export_repo import load_export_repo
from .runner import Chain, MatrixRenderer

MODEL_ID = "gemini-omni-1.1-flash-preview"
VARIANTS: tuple[VariantId, ...] = (
    "A_direct",
    "B_interp",
    "C_animatic",
    "D1_anchored",
    "D2_anchored_text",
)


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.experiments.keyframe_ab")
    p.add_argument("--export-dir", required=True, type=Path)
    p.add_argument("--project-id", required=True)
    p.add_argument("--scene", required=True)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--stage", choices=("keyframes", "render", "judge", "report"), required=True
    )
    p.add_argument("--samples", type=int, default=2)
    p.add_argument("--stride", type=int, default=3)
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument(
        "--gcp-project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "aug18-25-3")
    )
    p.add_argument("--bucket", default="aug18-25-3-veo-generators-media")
    p.add_argument("--workers", type=int, default=6)
    return p.parse_args()


def _repo(args: argparse.Namespace) -> Repo:
    blobs = GcsBlobStore(
        args.bucket,
        args.project_id,
        prefix="kf_experiments",
        client=storage.Client(project=args.gcp_project),
    )
    return load_export_repo(args.export_dir, args.project_id, blobs)


def _generator(repo: Repo, args: argparse.Namespace) -> KeyframeVideoGenerator:
    image_model = os.getenv("STORYBOARD_MODEL", "gemini-nano-banana-2.1")
    caps = VideoProviderCfg(
        provider="veo",
        model=MODEL_ID,
        max_reference_images=6,
        keyframe_stride_s=args.stride,
    )
    inner = GeminiVideoGenerator(caps=caps, project=args.gcp_project, location="global")
    sink = RepoKeyframeSink(repo)
    images = GeminiImageGenerator(model=image_model, project=args.gcp_project)
    vlm = GeminiVLMProvider("gemini-3.8-flash", project=args.gcp_project)
    renderer = KeyframeRenderer(
        images, vlm, sink, repo.blobs.get_bytes, RendererCfg(model=image_model)
    )
    builder = PlateBuilder(images, vlm, repo.blobs.get_bytes, "16:9")
    deps = KeyframeStageDeps(repo, renderer, sink, builder, image_model)

    @cache
    def plate_for(scene_id: str) -> ScenePlate:
        scene = repo.get_scene(scene_id)
        ctx = scene_context(deps, scene) if scene else None
        if ctx is None:
            raise ValueError(f"scene {scene_id} has no clips")
        return ctx.plate

    source = RenderingSource(renderer, plate_for)
    return KeyframeVideoGenerator(inner, repo, source, sink, caps)


def _shot_ids(repo: Repo, scene_id: str) -> tuple[str, ...]:
    shots = sorted(repo.list_shots(scene_id=scene_id), key=lambda s: s.clip_index or 0)
    return tuple(s.id for s in shots)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = _parse()
    repo = _repo(args)
    shot_ids = _shot_ids(repo, args.scene)
    if args.stage in ("judge", "report"):
        from .report import run_report_stage

        return run_report_stage(repo, args.out, shot_ids, args.stage == "judge")
    renderer = MatrixRenderer(repo, _generator(repo, args), args.out)
    renderer.render_keyframes(shot_ids)
    if args.stage == "render":
        variants = [v for v in VARIANTS if v in args.variants.split(",")]
        chains = [Chain(v, s, shot_ids) for s in range(args.samples) for v in variants]
        renderer.run(chains, args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

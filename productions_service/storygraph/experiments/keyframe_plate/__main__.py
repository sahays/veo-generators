"""CLI: run plate-anchored S8_KEYFRAMES offline on chosen scenes, then report before/after."""

from __future__ import annotations

import argparse
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.cloud import storage

from ...adapters.gemini_image import GeminiImageGenerator
from ...adapters.vlm import GeminiVLMProvider
from ...keyframes.plate.build import PlateBuilder
from ...keyframes.render.renderer import KeyframeRenderer, RendererCfg
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.stage import KeyframeStageDeps, KeyframeStageResult, run_scene
from ...repo import Repo
from ...store import GcsBlobStore, LocalBlobStore
from ..keyframe_ab.export_repo import load_export_repo
from .blobs import ReadThroughLocalBlobs
from .report import write_report

_log = logging.getLogger(__name__)


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="storygraph.experiments.keyframe_plate")
    p.add_argument("--export-dir", required=True, type=Path)
    p.add_argument("--project-id", required=True)
    p.add_argument("--scenes", required=True)
    p.add_argument("--before-dir", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--report-only", action="store_true")
    p.add_argument(
        "--gcp-project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "aug18-25-3")
    )
    p.add_argument("--bucket", default="aug18-25-3-veo-generators-media")
    return p.parse_args()


def _repo(args: argparse.Namespace) -> Repo:
    reader = GcsBlobStore(
        args.bucket, args.project_id, client=storage.Client(project=args.gcp_project)
    )
    writer = LocalBlobStore(args.out / "blobs", args.project_id)
    blobs = ReadThroughLocalBlobs(reader, writer, args.out / "cache")
    return load_export_repo(args.export_dir, args.project_id, blobs)


def _deps(repo: Repo, args: argparse.Namespace) -> KeyframeStageDeps:
    model = os.getenv("STORYBOARD_MODEL", "gemini-nano-banana-2.1")
    images = GeminiImageGenerator(model=model, project=args.gcp_project)
    vlm = GeminiVLMProvider("gemini-3.8-flash", project=args.gcp_project)
    sink = RepoKeyframeSink(repo)
    renderer = KeyframeRenderer(
        images,
        vlm,
        sink,
        repo.blobs.get_bytes,
        RendererCfg(model=model, aspect_ratio="16:9"),
    )
    builder = PlateBuilder(images, vlm, repo.blobs.get_bytes, "16:9")
    return KeyframeStageDeps(repo, renderer, sink, builder, model)


def _render(
    repo: Repo, args: argparse.Namespace, scene_ids: list[str]
) -> KeyframeStageResult:
    deps = _deps(repo, args)
    scenes = [s for s in repo.list_scenes() if s.id in scene_ids]
    result = KeyframeStageResult()
    with ThreadPoolExecutor(max_workers=len(scenes) or 1) as pool:
        for part in pool.map(lambda sc: run_scene(deps, sc), scenes):
            result.merge(part)
    return result


def _save_store(repo: Repo, out: Path) -> None:
    """Persist the in-memory keyframe sets/assets so `--report-only` can reload them."""
    dump = {
        col: repo.store.query(col)
        for col in ("keyframe_sets", "assets")
        if repo.store.query(col)
    }
    (out / "store_dump.json").write_text(
        json.dumps(dump, default=str), encoding="utf-8"
    )


def _load_store(repo: Repo, out: Path) -> None:
    path = out / "store_dump.json"
    if path.is_file():
        for col, rows in json.loads(path.read_text(encoding="utf-8")).items():
            for row in rows:
                repo.store.set(col, str(row["id"]), row)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    args = _parse()
    args.out.mkdir(parents=True, exist_ok=True)
    scene_ids = [s.strip() for s in args.scenes.split(",") if s.strip()]
    repo = _repo(args)
    if args.report_only:
        _load_store(repo, args.out)
    else:
        result = _render(repo, args, scene_ids)
        (args.out / "stage_result.json").write_text(
            json.dumps(result.__dict__, indent=2), encoding="utf-8"
        )
        _save_store(repo, args.out)
    write_report(repo, scene_ids, args.before_dir, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

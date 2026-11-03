"""Spike render stage: S8_PREVIZ (previz + E1 + E2) and the plate-keyframe D1 baseline."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google.cloud import storage

from ...adapters.gemini_image import GeminiImageGenerator
from ...adapters.gemini_video import GeminiVideoGenerator
from ...adapters.vlm import GeminiVLMProvider
from ...config import Config, VideoProviderCfg
from ...keyframes.plan.sampling.models import DENSE
from ...keyframes.stage.scene_plans import stored_scene_plans
from ...previz.factory import build_previz_deps
from ...previz.stage.stage import run_previz
from ...previz.variants.keyframe_restyle import animate_keyframes, store_frames
from ...repo import Repo
from ...repo.keyframe_sets import KeyframeSetRepo
from ...repo.previz_shots import PrevizShotRepo
from ...schema import Role
from ...schemas.previz import PrevizRun
from ...store import GcsBlobStore
from ...adapters.omni.package import RenderPackage
from ...schema import Shot
from ..keyframe_ab.export_repo import load_export_repo
from ..keyframe_ab.packages import base_package as exp_base_package
from ..keyframe_ab.packages import latest_run

_log = logging.getLogger(__name__)
OMNI_MODEL = "gemini-omni-1.1-flash-preview"
IMAGE_MODEL = "gemini-nano-banana-2.1"


def load_repo(
    export_dir: Path, project: str, gcp: str, bucket: str, kf_dump: Path
) -> Repo:
    """Export in memory + the plate-keyframe run's sets/assets (plates, keyframes)."""
    blobs = GcsBlobStore(
        bucket, project, prefix="kf_experiments", client=storage.Client(project=gcp)
    )
    repo = load_export_repo(export_dir, project, blobs)
    for col, rows in json.loads(kf_dump.read_text(encoding="utf-8")).items():
        for row in rows:
            repo.store.set(col, str(row["id"]), row)
    return repo


def adapters(
    gcp: str,
) -> tuple[Config, GeminiImageGenerator, GeminiVLMProvider, GeminiVideoGenerator]:
    cfg = Config.load()
    cfg.image.model = IMAGE_MODEL
    caps = VideoProviderCfg(provider="veo", model=OMNI_MODEL, max_reference_images=6)
    video = GeminiVideoGenerator(caps=caps, project=gcp, location="global")
    image = GeminiImageGenerator(model=IMAGE_MODEL, project=gcp)
    return cfg, image, GeminiVLMProvider("gemini-3.8-flash", project=gcp), video


def spike_base(repo: Repo) -> Callable[[Shot], RenderPackage]:
    """The export has no StyleGuide: rebuild each shot's package from its latest run
    (identical to what production sent, as in the keyframe experiment)."""
    return lambda shot: exp_base_package(repo, shot, latest_run(repo, shot.id))


def run_stage(repo: Repo, gcp: str, scenes: list[str], workdir: Path) -> PrevizRun:
    cfg, image, vlm, video = adapters(gcp)
    deps = build_previz_deps(repo, cfg, image, vlm, video, workdir)
    deps = replace(deps, variants=replace(deps.variants, base_for=spike_base(repo)))  # type: ignore[arg-type]
    run = PrevizRun(
        id="pzr_spike", created_by=Role.HUMAN, variant="both", scene_ids=scenes,
        started_at="spike",
    )  # fmt: skip
    return run_previz(deps, run)


def _d1_shot(repo: Repo, gcp: str, sid: str) -> dict[str, str]:
    cfg, image, vlm, video = adapters(gcp)
    deps = build_previz_deps(repo, cfg, image, vlm, video).variants
    shot = repo.get_shot(sid)
    scene = repo.get_scene(shot.scene_id) if shot else None
    ks = KeyframeSetRepo(repo.store).active_for_shot(sid)
    if deps is None or shot is None or scene is None or ks is None:
        return {"shot_id": sid, "error": "missing shot / keyframes"}
    sp = stored_scene_plans(repo, scene, sampling=DENSE)[sid]
    pngs = [repo.blobs.get_bytes(f.uri) for f in ks.frames]
    uris = store_frames(deps, sid, "d1plate", pngs)
    try:
        out = animate_keyframes(
            deps, sp.inp, sp.plan, spike_base(repo)(shot), uris, "d1plate"
        )
    except Exception as exc:  # spike: record and continue with the other shots
        return {"shot_id": sid, "error": f"{type(exc).__name__}: {exc}"[:300]}
    return {"shot_id": sid, "video_uri": out.video_uri}


def run_d1(repo: Repo, gcp: str, shot_ids: list[str]) -> list[dict[str, str]]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(lambda s: _d1_shot(repo, gcp, s), shot_ids))


def clip_index(repo: Repo, d1: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """`shot -> {variant: gs uri}` for previz, E1, E2 and D1."""
    out: dict[str, dict[str, str]] = {}
    for sid, ps in PrevizShotRepo(repo.store).active_by_shot().items():
        row = {"previz": ps.previz_video_uri or ""}
        row |= {v.variant: v.video_uri or "" for v in ps.variants}
        out[sid] = row
    for rec in d1:
        out.setdefault(rec["shot_id"], {})["D1_plate"] = rec.get("video_uri", "")
    return out

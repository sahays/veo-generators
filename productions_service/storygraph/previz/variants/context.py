"""Inputs shared by the restyle variants: adapters, storage and one shot's previz render."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...adapters.base import ImageGenerator, VideoGenerator, VLMProvider
from ...adapters.omni.package import RenderPackage
from ...config import Config
from ...keyframes.plan.models import KeyframePlan, PlanInput
from ...repo import Repo
from ...schema import Shot
from ...schemas.previz_scene import PrevizScene

Put = Callable[[str, bytes, str], str]  # (relative path, bytes, mime) -> stored URI


@dataclass(frozen=True)
class VariantDeps:
    repo: Repo
    cfg: Config
    video_gen: VideoGenerator
    image_gen: ImageGenerator
    vlm: VLMProvider
    put: Put
    style: str = ""
    image_model: str = ""
    # Base Omni package per shot; None = production composition (`variants.base`).
    base_for: Callable[[Shot], RenderPackage] | None = None


@dataclass(frozen=True)
class PrevizInput:
    """One rendered previz clip and the plan/scene it was built from."""

    shot: Shot
    inp: PlanInput
    plan: KeyframePlan
    scene: PrevizScene
    video_uri: str
    video: bytes


def frames_at(mp4: bytes, seconds: Sequence[float]) -> list[bytes]:
    """PNG frame at each second (clamped to the clip end by ffmpeg's -sseof fallback)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.mp4"
        src.write_bytes(mp4)
        return [
            _frame(src, Path(tmp) / f"f{i:03d}.png", t) for i, t in enumerate(seconds)
        ]


def _frame(src: Path, out: Path, t: float) -> bytes:
    for seek in (["-ss", f"{t:.3f}"], ["-sseof", "-0.05"]):
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *seek, "-i", str(src)]
        subprocess.run([*cmd, "-frames:v", "1", str(out)], check=False, timeout=60)
        if out.is_file() and out.stat().st_size > 64:
            return out.read_bytes()
    raise RuntimeError(f"no frame at t={t:.2f}s in previz clip")

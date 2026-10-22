"""Pipeline wiring: wrap the video generator when `video.render_strategy` is not `direct`."""

from __future__ import annotations

from ...adapters.base import VideoGenerator
from ...config import Config
from ...repo import Repo
from ..render.sink import RepoKeyframeSink
from .generator import KeyframeVideoGenerator
from .sources import StoredSource


def wrap_render_strategy(
    video_gen: VideoGenerator, repo: Repo, cfg: Config
) -> VideoGenerator:
    """`video_gen` unchanged for `direct`; otherwise a `KeyframeVideoGenerator` that renders
    from the approved S8_KEYFRAMES sets (`StoredSource`)."""
    if cfg.video.render_strategy == "direct":
        return video_gen
    caps = video_gen.caps.model_copy(
        update={"render_strategy": cfg.video.render_strategy}
    )
    return KeyframeVideoGenerator(
        video_gen, repo, StoredSource(repo), RepoKeyframeSink(repo), caps
    )

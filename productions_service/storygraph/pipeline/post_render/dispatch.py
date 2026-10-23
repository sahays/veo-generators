"""`audio.mode` dispatch for post-QA audio work and the S10 stem renderer."""

from __future__ import annotations

from ...assembly.assembler import StemRenderer
from ...assembly.readiness import ReadyShot
from ...assembly.stem_clips import StemClips, render_stem_clips
from ...audio.stems import RenderTools
from ...config import Config
from ...repo import Repo
from .stems_stage import apply_stems
from .voiceover_stage import apply_voiceover


def apply_audio_post(repo: Repo, cfg: Config) -> list[str]:
    """Run the configured post-QA audio stage; returns the run ids it processed."""
    if cfg.audio.mode == "voiceover_duck":
        return apply_voiceover(repo, cfg)
    if cfg.audio.mode == "stems":
        return apply_stems(repo, cfg)
    return []


def stem_renderer_for(repo: Repo, cfg: Config) -> StemRenderer | None:
    """S10 renders clips from stems only in `stems` mode with a real video provider."""
    if cfg.audio.mode != "stems" or cfg.video.provider == "mock":
        return None
    tools = RenderTools()

    def _render(ready: list[ReadyShot], pictures: list[bytes]) -> StemClips:
        return render_stem_clips(
            repo, ready, pictures, (cfg.audio, cfg.assembly), tools
        )

    return _render

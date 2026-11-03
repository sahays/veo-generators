"""Dependencies of the S8_PREVIZ stage (adapters are injected; nothing here does I/O)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ...keyframes.plan.models import KeyframePlan, PlanInput
from ...repo import Repo
from ...schema import Scene
from ...schemas.previz import PrevizLayout
from ...schemas.previz_scene import LocationLayout, PrevizScene
from ..variants.context import VariantDeps

STAGE_ID = "S8_PREVIZ"


class RenderOutcome(Protocol):
    ok: bool
    mp4_path: Path | None
    seconds: float
    blender_version: str | None

    @property
    def failure_text(self) -> str | None: ...


class PrevizRenderer(Protocol):
    def version(self) -> str | None: ...

    def render(self, scene: PrevizScene, workdir: Path) -> RenderOutcome: ...


LayoutSource = Callable[[Scene], PrevizLayout]
SceneBuilder = Callable[[PlanInput, KeyframePlan, LocationLayout, Scene], PrevizScene]


@dataclass(frozen=True)
class PrevizStageDeps:
    repo: Repo
    renderer: PrevizRenderer
    layouts: (
        LayoutSource  # active (cached / re-estimated) layout of the scene's location
    )
    build_scene: SceneBuilder  # pure: plan + layout -> PrevizScene
    workdir: Path
    variants: VariantDeps | None = None  # None: previz_only is all that can run
    scene_workers: int = 2
    shot_workers: int = 2

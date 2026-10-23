"""Scene-level planning: every clip of a scene planned against the scene plate's layout.

A shot's plan depends on its scene: set-piece positions come from the scene's locked plate
(`PlateSpec` key -> stored layout) and each character starts where the previous clip of the
scene left it (`PlanInput.start_x`). Planning the whole scene in clip order is the single
source of truth for plan hashes — the stage, the video strategies and the API all use it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...repo import Repo
from ...schema import Scene, Shot
from ..plan.graph_source import build_plan_input
from ..plan.models import KeyframePlan, PlanInput
from ..plan.planner import plan_keyframes
from ..plate.spec import PlateSpec, plate_spec
from ..render.sink import PlateStore, RepoKeyframeSink


@dataclass(frozen=True)
class ShotPlan:
    shot: Shot
    inp: PlanInput
    plan: KeyframePlan


def scene_shots(repo: Repo, scene: Scene) -> list[Shot]:
    """The scene's clips in clip order (shots without a clip index are not clips)."""
    shots = [s for s in repo.list_shots(scene_id=scene.id) if s.clip_index is not None]
    return sorted(shots, key=lambda s: s.clip_index or 0)


def scene_spec(inputs: list[PlanInput]) -> PlateSpec:
    """Plate spec from layout-free plans of every clip (set pieces need the whole scene)."""
    return plate_spec([(inp, plan_keyframes(inp)) for inp in inputs])


def chain_plans(
    shots: list[Shot], inputs: list[PlanInput], layout: dict[str, float]
) -> list[ShotPlan]:
    """Plan clips in order with the scene layout, carrying character x across clips."""
    out: list[ShotPlan] = []
    start: dict[str, float] = {}
    for shot, base in zip(shots, inputs, strict=True):
        inp = base.model_copy(update={"layout": dict(layout), "start_x": dict(start)})
        plan = plan_keyframes(inp)
        if plan.keyframes:
            start |= {c.entity_id: c.x for c in plan.keyframes[-1].characters}
        out.append(ShotPlan(shot, inp, plan))
    return out


@dataclass(frozen=True)
class ScenePlanning:
    spec: PlateSpec | None
    shots: list[Shot]
    inputs: list[PlanInput]


def scene_planning(repo: Repo, scene: Scene) -> ScenePlanning:
    shots = scene_shots(repo, scene)
    inputs = [build_plan_input(repo, scene, s) for s in shots]
    return ScenePlanning(scene_spec(inputs) if inputs else None, shots, inputs)


def stored_scene_plans(
    repo: Repo, scene: Scene, plates: PlateStore | None = None
) -> dict[str, ShotPlan]:
    """`shot id -> ShotPlan` using the scene's STORED plate layout ({} before S8 ran)."""
    planning = scene_planning(repo, scene)
    if planning.spec is None:
        return {}
    layout = (plates or RepoKeyframeSink(repo)).load_layout(planning.spec)
    plans = chain_plans(planning.shots, planning.inputs, layout)
    return {sp.shot.id: sp for sp in plans}


def shot_plan(repo: Repo, scene: Scene, shot: Shot) -> tuple[PlanInput, KeyframePlan]:
    """The current plan of one clip (as S8_KEYFRAMES derives it)."""
    found = stored_scene_plans(repo, scene).get(shot.id)
    if found is None:
        raise ValueError(f"shot {shot.id} is not a clip of scene {scene.id}")
    return found.inp, found.plan

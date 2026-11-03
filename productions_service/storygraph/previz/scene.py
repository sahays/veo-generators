"""PrevizScene assembler: layout + camera rig + blocking + render settings (pure).

`build_previz_scene` is deterministic given its inputs. The master camera is the
calibrated one from the camera stage when given (else the synthetic master): it drives
blocking projection, the WS framing and the shot-camera family, and - when the scene has a
plate - the `projection` that paints `plate.png` onto the set. Per-object ID and depth
passes are always requested at 1 fps (one per keyframe second). `PrevizSceneBuilder` binds
the project's blob store (reference sheets -> colours + aspects, cached per URI), the
aspect ratio and fps, for callers that only hold the plan, the layout and the scene.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ..keyframes.plan.models import KeyframePlan, PlanInput
from ..keyframes.plan.timing import second_index
from ..repo import Repo
from ..schema import Scene
from ..schemas.previz_scene import (
    BlockingTrack,
    CameraRig,
    LocationLayout,
    PrevizScene,
    ProjectionSpec,
    RenderPass,
    RenderSettings,
    Vec3,
)
from .blocking.project import Aspect
from .blocking.tracks import blocking_track
from .camera.rig import camera_rig, master_rig
from .layout.cache import input_aspects, input_colors

LONG_SIDE: Final[int] = 480
SHORT_SIDE: Final[int] = 270
PLATE_FILE: Final[str] = "plate.png"
PASSES: Final[tuple[RenderPass, ...]] = ("object_id", "depth")
PASS_FPS: Final[int] = 1


def focus_point(
    inp: PlanInput, plan: KeyframePlan, blocking: BlockingTrack
) -> Vec3 | None:
    """Mid-clip position of the acting character (else the first), z = its height."""
    if not blocking.characters or not plan.keyframes:
        return None
    mid = plan.keyframes[len(plan.keyframes) // 2]
    actor = inp.beats[mid.beat_index].actor_id if inp.beats else ""
    track = next(
        (c for c in blocking.characters if c.entity_id == actor), blocking.characters[0]
    )
    key = track.keys[min(second_index(mid.t), len(track.keys) - 1)]
    return Vec3(x=key.position.x, y=key.position.y, z=track.height_m)


def _render(aspect: Aspect, fps: int) -> RenderSettings:
    wide = aspect == "16:9"
    return RenderSettings(
        width=LONG_SIDE if wide else SHORT_SIDE,
        height=SHORT_SIDE if wide else LONG_SIDE,
        fps=fps,
        passes=list(PASSES),
        pass_fps=PASS_FPS,
    )


def build_previz_scene(
    inp: PlanInput,
    plan: KeyframePlan,
    layout: LocationLayout,
    colors: dict[str, str],
    aspect: Aspect = "16:9",
    fps: int = 24,
    *,
    master: CameraRig | None = None,
    aspects: Mapping[str, float] | None = None,
    has_plate: bool = False,
) -> PrevizScene:
    """Everything the Blender script needs for one clip (`has_plate`: `plate.png` is
    written next to layout.json, so it is projected from the master camera)."""
    blocking = blocking_track(inp, plan, layout, colors, aspect, master, aspects)
    base = master_rig(layout, aspect, master)
    focus = focus_point(inp, plan, blocking)
    return PrevizScene(
        layout=layout,
        camera=camera_rig(layout, inp.camera, focus, inp.duration_s, aspect, base),
        blocking=blocking,
        render=_render(aspect, fps),
        projection=ProjectionSpec(image_file=PLATE_FILE, camera=base)
        if has_plate
        else None,
    )


class PrevizSceneBuilder:
    """`build_previz_scene` bound to a project's blobs (sheet colours + aspects), aspect
    and fps."""

    def __init__(self, repo: Repo, aspect: Aspect = "16:9", fps: int = 24) -> None:
        self.repo, self.aspect, self.fps = repo, aspect, fps

    def __call__(
        self,
        inp: PlanInput,
        plan: KeyframePlan,
        layout: LocationLayout,
        scene: Scene,
        master: CameraRig | None = None,
        has_plate: bool = False,
    ) -> PrevizScene:
        if scene.id != inp.scene_id:
            raise ValueError(f"plan of {inp.scene_id} built for scene {scene.id}")
        fetch = self.repo.blobs.get_bytes
        return build_previz_scene(
            inp,
            plan,
            layout,
            input_colors(fetch, [inp]),
            self.aspect,
            self.fps,
            master=master,
            aspects=input_aspects(fetch, [inp]),
            has_plate=has_plate,
        )

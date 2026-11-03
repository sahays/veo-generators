"""Per-location layout requests and the versioned layout cache.

A location is shared by every scene set there, so its set pieces are the UNION of each
scene's set pieces (`keyframes.plate.spec.set_piece_ids`). The plate read is the one of the
primary scene: a scene with a plate, covering the most set pieces (ties -> lowest scene id).
`layout_for_location` returns the active `PrevizLayout` when its `source_hash` matches the
request, else estimates once and stores a new active version.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...keyframes.plan.models import KeyframePlan, PlanInput
from ...keyframes.plan.planner import plan_keyframes
from ...keyframes.plate.spec import set_piece_ids
from ...keyframes.render.sink import RepoKeyframeSink
from ...keyframes.stage.scene_plans import scene_planning
from ...repo import Repo
from ...repo.previz_layouts import PrevizLayoutRepo
from ...schema import Scene
from ...schemas.base import Role
from ...schemas.previz import PrevizLayout
from ...schemas.previz_scene import CameraRig, Room
from ..blocking.project import Aspect
from .colors import entity_aspects, entity_colors
from .estimate import LayoutEstimator, LayoutRequest, source_hash

_log = logging.getLogger(__name__)
ScenePairs = Sequence[tuple[PlanInput, KeyframePlan]]
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class ScenePlate:
    png: bytes | None = None
    layout_x: Mapping[str, float] = field(default_factory=dict)


def _primary(ids: Mapping[str, set[str]], plates: Mapping[str, ScenePlate]) -> str:
    def rank(sid: str) -> tuple[int, int, str]:
        has_plate = sid in plates and plates[sid].png is not None
        return (0 if has_plate else 1, -len(ids[sid]), sid)

    return min(ids, key=rank)


def _moved_ids(scenes: Mapping[str, ScenePairs]) -> set[str]:
    """Objects that MOVE in any clip at the location (held, or their unheld placement
    changes): props everywhere, never set pieces, so they are never drawn twice. Furniture
    that is merely acted on (a bench worked at, a cabinet opened) stays a set piece."""
    out: set[str] = set()
    for pairs in scenes.values():
        places: dict[str, set[str]] = {}
        for _, plan in pairs:
            for o in (o for k in plan.keyframes for o in k.objects):
                if o.holder_id:
                    out.add(o.entity_id)
                places.setdefault(o.entity_id, set()).add(o.placement)
        out |= {oid for oid, seen in places.items() if len(seen) > 1}
    return out


def _refs(inputs: Sequence[PlanInput]) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for inp in inputs:
        refs |= {c.entity_id: c.ref_uri for c in inp.cast}
        refs |= {o.entity_id: o.ref_uri for o in inp.objects}
    return refs


def input_colors(
    fetch: Callable[[str], bytes], inputs: Sequence[PlanInput]
) -> dict[str, str]:
    """Colour of every cast member and object across `inputs` (from its reference sheet)."""
    return entity_colors(fetch, _refs(inputs))


def input_aspects(
    fetch: Callable[[str], bytes], inputs: Sequence[PlanInput]
) -> dict[str, float]:
    """Subject width/height of every readable reference sheet across `inputs`."""
    return entity_aspects(fetch, _refs(inputs))


@dataclass(frozen=True)
class Calibration:
    """Optional camera-stage outputs: the plate's calibrated camera and room size."""

    master: CameraRig | None = None
    room: Room | None = None


def location_request(
    scenes: Mapping[str, ScenePairs],
    plates: Mapping[str, ScenePlate],
    colors: Mapping[str, str],
    aspect: Aspect = "16:9",
    aspects: Mapping[str, float] | None = None,
    calibration: Calibration | None = None,
) -> LayoutRequest:
    """Layout request for the location shared by `scenes` (scene id -> its clip plans)."""
    moved = _moved_ids(scenes)
    ids = {
        sid: set(set_piece_ids(pairs)) - moved for sid, pairs in scenes.items() if pairs
    }
    if not ids:
        raise ValueError("location_request needs at least one scene with clips")
    union = set().union(*ids.values())
    objects = {
        o.entity_id: o
        for pairs in scenes.values()
        for inp, _ in pairs
        for o in inp.objects
        if o.entity_id in union
    }
    primary = _primary(ids, plates)
    inp = scenes[primary][0][0]
    plate = plates.get(primary, ScenePlate())
    cal, shapes = calibration or Calibration(), aspects or {}
    return LayoutRequest(
        location_id=inp.location_id,
        name=inp.location_name,
        description=inp.location_description,
        location_ref_uri=inp.location_ref_uri,
        plate_png=plate.png,
        plate_layout_x=dict(plate.layout_x),
        set_pieces=tuple(objects[i] for i in sorted(objects)),
        ref_colors={i: colors[i] for i in sorted(objects) if i in colors},
        aspect=aspect,
        ref_aspects={i: shapes[i] for i in sorted(objects) if i in shapes},
        master=cal.master,
        room=cal.room,
    )


def _log_event(what: str, why: str, location_id: str, layout_id: str) -> None:
    _log.info(
        what,
        extra={
            "who": "storygraph.previz",
            "where": "previz.layout.cache",
            "what": f"{what} {layout_id}",
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": "compare source_hash with the active PrevizLayout",
            "location_id": location_id,
        },
    )


def layout_for_location(
    layouts: PrevizLayoutRepo, estimator: LayoutEstimator, req: LayoutRequest
) -> PrevizLayout:
    """Active layout when its inputs are unchanged, else one new estimated version."""
    wanted = source_hash(req)
    active = layouts.active_for_location(req.location_id)
    if active is not None and active.layout.source_hash == wanted:
        _log_event(
            "previz_layout_reused", "inputs unchanged", req.location_id, active.id
        )
        return active
    why = "no layout yet" if active is None else "layout inputs changed"
    draft = PrevizLayout(
        id=f"pzl_{req.location_id}_draft",
        created_by=Role.PIPELINE,
        location_id=req.location_id,
        layout=estimator.estimate_request(req),
    )
    stored = layouts.create(draft, why=why)
    _log_event("previz_layout_estimated", why, req.location_id, stored.id)
    return stored


def _location_lock(location_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(location_id, threading.Lock())


def _scene_inputs(repo: Repo, scene: Scene) -> tuple[ScenePairs, ScenePlate | None]:
    """Layout-free clip plans of one scene and its stored plate (None before S8 ran)."""
    planning = scene_planning(repo, scene)
    pairs = [(inp, plan_keyframes(inp)) for inp in planning.inputs]
    stored = RepoKeyframeSink(repo).load_plate(planning.spec) if planning.spec else None
    return pairs, ScenePlate(stored.png, dict(stored.layout)) if stored else None


def layout_for_scene(
    repo: Repo,
    estimator: LayoutEstimator,
    scene: Scene,
    aspect: Aspect = "16:9",
    calibration: Calibration | None = None,
) -> PrevizLayout:
    """The (cached / versioned) layout of `scene`'s location, shared by all its scenes.

    Thread-safe per location: concurrent scenes of one location estimate at most once.
    `calibration` (camera stage) replaces the synthetic master camera / VLM room size."""
    scenes: dict[str, ScenePairs] = {}
    plates: dict[str, ScenePlate] = {}
    for sc in repo.list_scenes():
        if sc.location_id != scene.location_id:
            continue
        pairs, plate = _scene_inputs(repo, sc)
        scenes[sc.id] = pairs
        if plate is not None:
            plates[sc.id] = plate
    inputs = [inp for pairs in scenes.values() for inp, _ in pairs]
    fetch = repo.blobs.get_bytes
    colors, aspects = input_colors(fetch, inputs), input_aspects(fetch, inputs)
    req = location_request(scenes, plates, colors, aspect, aspects, calibration)
    with _location_lock(scene.location_id):
        return layout_for_location(PrevizLayoutRepo(repo.store), estimator, req)

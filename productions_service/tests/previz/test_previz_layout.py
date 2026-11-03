"""Previz location layout: determinism, plate-x agreement, overlaps, versioned cache, colours."""

from __future__ import annotations

import io
import itertools

import pytest
from PIL import Image

from storygraph.adapters.mock import MockVLMProvider
from storygraph.keyframes.plan.models import (
    BeatSpan,
    ObjectInput,
    PlanInput,
    StateSnapshot,
)
from storygraph.keyframes.plan.planner import plan_keyframes
from storygraph.previz.blocking.project import master_camera, to_image
from storygraph.previz.layout.cache import (
    ScenePlate,
    layout_for_location,
    location_request,
)
from storygraph.previz.layout.colors import dominant_color
from storygraph.previz.layout.estimate import (
    LayoutEstimator,
    LayoutObs,
    LayoutRequest,
    PieceObs,
    RoomObs,
    build_layout,
)
from storygraph.repo.previz_layouts import PrevizLayoutRepo
from storygraph.schemas.previz_scene import LocationLayout, Vec3
from storygraph.store import MemoryStore

_PIECES = (
    ObjectInput(entity_id="obj_bench", name="Workbench"),
    ObjectInput(entity_id="obj_shelf", name="Shelf"),
    ObjectInput(entity_id="obj_lamp", name="Lamp"),
)


class CountingVLM:
    """Returns one fixed observation and counts calls (stands in for Gemini)."""

    def __init__(self, obs: LayoutObs) -> None:
        self.obs, self.calls = obs, 0

    def review(self, images: list[bytes], prompt: str, schema: type) -> LayoutObs:
        self.calls += 1
        return self.obs


def _obs() -> LayoutObs:
    return LayoutObs(
        room=RoomObs(width_m=9.0, depth_m=6.0, height_m=3.0, floor_color="#806040"),
        pieces=[
            PieceObs(name="Workbench", x=0.7, depth=0.8),
            PieceObs(name="Shelf", x=0.2, depth=1.0),
            PieceObs(name="Lamp", x=0.45, depth=0.3),
        ],
    )


def _req(plate: bytes = b"plate-v1", **kw: object) -> LayoutRequest:
    base: dict[str, object] = {
        "location_id": "loc_ws",
        "name": "Workshop",
        "description": "a cluttered workshop",
        "plate_png": plate,
        "plate_layout_x": {"obj_bench": 0.68},
        "set_pieces": _PIECES,
        "ref_colors": {"obj_bench": "#aa5522"},
    }
    return LayoutRequest(**(base | kw))  # type: ignore[arg-type]


def _image_x(layout: LocationLayout, eid: str) -> float:
    cam = master_camera(layout.room)
    p = next(s for s in layout.set_pieces if s.entity_id == eid)
    return to_image(cam, Vec3(x=p.position.x, y=p.position.y, z=p.size.z / 2))[0]


def test_same_answer_gives_identical_layout_and_hash() -> None:
    a = build_layout(_req(), _obs())
    b = build_layout(_req(), _obs().model_copy(deep=True))
    assert a.model_dump_json() == b.model_dump_json()
    assert (
        a.source_hash
        == build_layout(_req(set_pieces=_PIECES[::-1]), _obs()).source_hash
    )
    assert a.source_hash != build_layout(_req(plate=b"plate-v2"), _obs()).source_hash
    bench = next(p for p in a.set_pieces if p.entity_id == "obj_bench")
    assert bench.color == "#aa5522"  # sheet colour wins
    assert a.room.floor_color == "#806040"


def test_projected_pieces_reproduce_plate_x_and_plate_beats_vlm() -> None:
    layout = build_layout(_req(), _obs())
    assert _image_x(layout, "obj_bench") == pytest.approx(
        0.68, abs=0.02
    )  # stored plate x
    assert _image_x(layout, "obj_shelf") == pytest.approx(0.2, abs=0.02)  # VLM x
    assert _image_x(layout, "obj_lamp") == pytest.approx(0.45, abs=0.02)
    depth = {p.entity_id: p.position.y for p in layout.set_pieces}
    assert depth["obj_lamp"] < depth["obj_bench"] < depth["obj_shelf"]  # near..far kept


def test_colliding_pieces_are_pushed_apart_inside_the_room() -> None:
    same = [PieceObs(name=n, x=0.95, depth=0.5) for n in ("Workbench", "Shelf", "Lamp")]
    layout = build_layout(_req(plate_layout_x={}), LayoutObs(pieces=same))
    half = layout.room.width / 2
    for a, b in itertools.combinations(layout.set_pieces, 2):
        assert abs(a.position.x - b.position.x) >= (a.size.x + b.size.x) / 2 - 1e-6
    assert all(
        abs(p.position.x) + p.size.x / 2 <= half + 1e-6 for p in layout.set_pieces
    )


def test_cache_reuses_active_version_and_versions_on_change() -> None:
    repo = PrevizLayoutRepo(MemoryStore(project_id="p"))
    vlm = CountingVLM(_obs())
    est = LayoutEstimator(vlm, fetch=lambda uri: b"")
    first = layout_for_location(repo, est, _req())
    again = layout_for_location(repo, est, _req())
    assert (first.id, again.id, vlm.calls) == ("pzl_loc_ws_1", "pzl_loc_ws_1", 1)
    changed = layout_for_location(repo, est, _req(plate=b"plate-v2"))
    assert (changed.id, changed.version, vlm.calls) == ("pzl_loc_ws_2", 2, 2)
    statuses = {p.id: p.set_status for p in repo.list("loc_ws")}
    assert statuses == {"pzl_loc_ws_1": "superseded", "pzl_loc_ws_2": "active"}
    assert [p.id for p in repo.list_active()] == ["pzl_loc_ws_2"]


def test_offline_mock_vlm_places_every_piece_once() -> None:
    est = LayoutEstimator(MockVLMProvider(), fetch=lambda uri: b"")
    layout = est.estimate_request(_req(plate_layout_x={}))
    assert sorted(p.entity_id for p in layout.set_pieces) == sorted(
        o.entity_id for o in _PIECES
    )
    xs = sorted(_image_x(layout, p.entity_id) for p in layout.set_pieces)
    assert xs == pytest.approx([0.25, 0.5, 0.75], abs=0.02)  # mock spreads listed names


def _png(
    size: tuple[int, int], boxes: list[tuple[tuple[int, int, int, int], str]]
) -> bytes:
    img = Image.new("RGB", size, "#fafafa")
    for box, colour in boxes:
        img.paste(Image.new("RGB", (box[2] - box[0], box[3] - box[1]), colour), box[:2])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_dominant_color_ignores_background_and_is_stable_on_garbage() -> None:
    sheet = _png(
        (200, 200), [((20, 20, 140, 140), "#c03020"), ((150, 150, 170, 170), "#2040c0")]
    )
    r, g, b = (int(dominant_color(sheet)[i : i + 2], 16) for i in (1, 3, 5))
    assert (
        r > 150 and g < 80 and b < 60
    )  # the red body, not the white page or blue detail
    grey = _png((50, 50), [((0, 0, 50, 50), "#808080")])
    assert dominant_color(grey, "obj_x") == dominant_color(b"not a png", "obj_x")
    assert dominant_color(b"not a png", "obj_x") != dominant_color(
        b"not a png", "obj_y"
    )


def _scene_input(scene_id: str, object_ids: list[str]) -> PlanInput:
    snap = StateSnapshot(
        order=0, states={o: {"location": "loc_ws"} for o in object_ids}
    )
    return PlanInput(
        project_id="p",
        scene_id=scene_id,
        shot_id=f"shot_{scene_id}",
        clip_index=1,
        duration_s=3.0,
        location_id="loc_ws",
        location_name="Workshop",
        objects=[o for o in _PIECES if o.entity_id in object_ids],
        snapshots=[snap, snap],
    )


def test_location_request_unions_scenes_and_reads_the_plated_scene() -> None:
    a = _scene_input("scn_a", ["obj_bench", "obj_shelf"])
    b = _scene_input("scn_b", ["obj_bench", "obj_lamp"])
    scenes = {"scn_a": [(a, plan_keyframes(a))], "scn_b": [(b, plan_keyframes(b))]}
    plates = {"scn_b": ScenePlate(b"plate-b", {"obj_bench": 0.4})}
    req = location_request(scenes, plates, {"obj_lamp": "#112233"})
    assert [o.entity_id for o in req.set_pieces] == [
        "obj_bench",
        "obj_lamp",
        "obj_shelf",
    ]
    assert (req.plate_png, dict(req.plate_layout_x)) == (b"plate-b", {"obj_bench": 0.4})
    assert dict(req.ref_colors) == {"obj_lamp": "#112233"}


def test_object_carried_in_any_scene_is_never_a_static_set_piece() -> None:
    a = _scene_input("scn_a", ["obj_bench", "obj_shelf"])
    b = _scene_input("scn_b", ["obj_bench", "obj_lamp", "obj_shelf"])
    carried = StateSnapshot(
        order=0,
        states={
            "obj_bench": {"location": "loc_ws"},
            "obj_lamp": {"location": "loc_ws"},
            "obj_shelf": {"location": "loc_ws"},
            "char_x": {"location": "loc_ws", "holding": "obj_shelf"},
        },
    )
    work = BeatSpan(
        index=0,
        t_start=0,
        t_end=2,
        actor_id="char_x",
        target_id="obj_bench",
        action="X works at the bench.",
    )
    b = b.model_copy(update={"snapshots": [carried, carried], "beats": [work]})
    scenes = {"scn_a": [(a, plan_keyframes(a))], "scn_b": [(b, plan_keyframes(b))]}
    req = location_request(scenes, {}, {})
    # shelf is carried in scn_b -> prop everywhere; bench is only worked at -> stays set
    assert [o.entity_id for o in req.set_pieces] == ["obj_bench", "obj_lamp"]

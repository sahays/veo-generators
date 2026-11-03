"""Previz object typing + proportions: kinds, sheet aspect, plate footprint, wall openings."""

from __future__ import annotations

import io
from collections.abc import Sequence

import pytest
from PIL import Image, ImageDraw

from storygraph.keyframes.plan.models import ObjectInput
from storygraph.previz.blocking.project import (
    camera_from_rig,
    hit_plane,
    master_camera,
    to_image,
    world_x,
)
from storygraph.previz.layout.estimate import (
    LayoutObs,
    LayoutRequest,
    PieceObs,
    build_layout,
)
from storygraph.previz.layout.kinds import classify
from storygraph.previz.layout.openings import (
    THICK,
    OpeningObs,
    place_opening,
    place_openings,
)
from storygraph.previz.layout.proportions import (
    Footprint,
    from_box_2d,
    measure,
    piece_size,
    prop_shape,
)
from storygraph.previz.layout.sheet_shape import subject_aspect
from storygraph.schemas.previz_scene import CameraRig, Room, Vec3

_ROOM = Room(width=8.0, depth=6.0, height=3.0)


@pytest.mark.parametrize(
    ("name", "description", "vlm", "kind", "source"),
    [
        ("Blue Cabinet", "", None, "cabinet", "name"),
        ("Blue Cabinet", "", "shelf", "cabinet", "name"),  # rules beat the VLM
        ("Desk Lamp", "", None, "cylinder", "name"),  # head noun, not "desk"
        ("Tool Chest", "", None, "toolbox", "name"),  # phrase before "chest"
        ("Old Trunk", "", None, "chest", "name"),
        ("Workbench", "", None, "bench", "name"),
        ("Brass Key", "", None, "box", "name"),
        ("Thing", "a three-legged stool, worn", None, "stool", "description"),
        ("Thing", "a key resting on the cabinet", None, "box", "description"),
        ("Gizmo", "", "shelf", "shelf", "vlm"),
        ("Gizmo", "", None, "box", "default"),
    ],
)
def test_kind_classification_table(
    name: str, description: str, vlm: str | None, kind: str, source: str
) -> None:
    got = classify(name, description, vlm)
    assert (got.kind, got.source) == (kind, source)


def test_workbench_and_seating_bench_share_kind_not_size() -> None:
    work, seat = classify("Workbench"), classify("Garden Bench")
    assert work.kind == seat.kind == "bench"
    assert work.dims[2] > seat.dims[2] + 0.3  # worktop height vs seat height


def _sheet(
    rects: list[tuple[int, int, int, int]],
    clutter: Sequence[tuple[tuple[int, int, int, int], str]] = (),
) -> bytes:
    img = Image.new("RGB", (300, 200), "#ecd3b1")  # pastel diorama background
    draw = ImageDraw.Draw(img)
    for box, colour in clutter:
        draw.rectangle(box, fill=colour)
    for r in rects:
        draw.rectangle(r, fill="#2050b0")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_sheet_aspect_is_the_largest_view_of_a_turnaround() -> None:
    single = _sheet([(110, 40, 169, 159)])  # 60 x 120
    assert subject_aspect(single) == pytest.approx(0.5, abs=0.05)
    turnaround = _sheet([(20, 40, 109, 159), (140, 40, 179, 159), (220, 70, 259, 159)])
    assert subject_aspect(turnaround) == pytest.approx(0.75, abs=0.05)  # 90 x 120
    assert subject_aspect(_sheet([])) is None
    desk = [((0, 150, 299, 199), "#8a5a30"), ((200, 20, 290, 60), "#d0d040")]
    cluttered = _sheet([(110, 40, 169, 159)], desk)  # desk strip + pencil tin, unkeyed
    assert subject_aspect(cluttered) == pytest.approx(0.5, abs=0.05)
    assert subject_aspect(b"not a png") is None


def _bbox(cam_rig: CameraRig | None, corners: list[Vec3]) -> list[float]:
    cam = master_camera(_ROOM, rig=cam_rig)
    pts = [to_image(cam, p) for p in corners]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _box_2d(box: list[float]) -> list[float]:
    """[x0, y0, x1, y1] (0..1) -> Gemini's [ymin, xmin, ymax, xmax] (0..1000)."""
    return [box[1] * 1000, box[0] * 1000, box[3] * 1000, box[2] * 1000]


def test_gemini_box_2d_is_y_first_on_a_1000_grid() -> None:
    assert from_box_2d([520, 90, 860, 370]) == pytest.approx((0.09, 0.52, 0.37, 0.86))
    assert from_box_2d([0.52, 0.09, 0.86, 0.37]) == pytest.approx(
        (0.09, 0.52, 0.37, 0.86)
    )
    assert from_box_2d([500, 500, 500, 600]) is None  # degenerate
    assert from_box_2d(None) is None


_YAWED = CameraRig(
    position=Vec3(x=-1.5, y=-3.0, z=1.6),
    target=Vec3(x=0.5, y=3.0, z=0.8),
    lens_mm=24.0,
    shift_y=0.05,
)


@pytest.mark.parametrize(("rig", "x0", "x1"), [(None, 0.4, 1.2), (_YAWED, 0.79, 0.81)])
def test_plate_footprint_converts_to_metres(
    rig: CameraRig | None, x0: float, x1: float
) -> None:
    face = [Vec3(x=x, y=3.0, z=z) for x in (x0, x1) for z in (0.0, 0.9)]
    box = _bbox(rig, face)
    cam = master_camera(_ROOM, rig=rig)
    fp = measure(cam, (box[0], box[1], box[2], box[3]), fallback_y=5.0, depth=0.0)
    assert fp.front_y == pytest.approx(3.0, abs=0.05)
    assert fp.height_m == pytest.approx(0.9, abs=0.05)
    if rig is None:  # an unyawed camera sees the face's true width
        assert fp.width_m == pytest.approx(0.8, abs=0.03)
    cut = measure(cam, (box[0], box[1], box[2], 1.0), fallback_y=5.0, depth=0.0)
    assert cut.front_y is None  # contact out of frame -> caller's fallback depth


def test_calibrated_camera_round_trips_plate_points() -> None:
    cam = camera_from_rig(_YAWED)
    p = Vec3(x=1.3, y=4.2, z=0.7)
    x, y = to_image(cam, p)
    assert world_x(cam, x, p.y, p.z) == pytest.approx(p.x, abs=1e-6)
    hit = hit_plane(cam, x, y, 1, p.y)
    assert hit is not None and hit.z == pytest.approx(p.z, abs=1e-6)


def test_cabinet_prop_is_a_drawer_cabinet_not_a_locker() -> None:
    cab = ObjectInput(
        entity_id="obj_cab",
        name="Blue Cabinet",
        description="a cabinet with two drawers",
    )
    plain = prop_shape(cab, None, _ROOM)
    assert plain.kind == "cabinet" and plain.params == {"drawers": 2.0}
    assert (plain.size.x, plain.size.y, plain.size.z) == pytest.approx((0.6, 0.45, 0.8))
    tall_sheet = prop_shape(cab, 0.35, _ROOM)  # a narrow sheet cannot stretch it upward
    assert tall_sheet.size.z == pytest.approx(0.8) and tall_sheet.size.x < 0.6
    no_count = prop_shape(cab.model_copy(update={"description": ""}), None, _ROOM)
    assert no_count.params == {"drawers": 3.0}


def test_plate_footprint_scales_within_kind_bounds() -> None:
    dims = classify("Blue Cabinet").dims
    big = piece_size(dims, 0.75, Footprint(3.0, 1.2, 1.6), _ROOM)
    assert big.z == pytest.approx(1.6) and big.x == pytest.approx(1.2)
    huge = piece_size(dims, 0.75, Footprint(3.0, 9.0, 9.0), _ROOM)
    assert huge.z == pytest.approx(2 * dims[2])  # bounded at 2x the type default


def test_door_on_back_wall_and_window_on_side_wall() -> None:
    door_face = [
        Vec3(x=x, y=_ROOM.depth, z=z) for x in (-1.0, -0.1) for z in (0.0, 2.1)
    ]
    door = place_opening(
        _ROOM,
        master_camera(_ROOM),
        OpeningObs(kind="door", wall="back", box_2d=_box_2d(_bbox(None, door_face))),
        "d",
        "Door",
    )
    assert door.position.y == pytest.approx(_ROOM.depth - THICK / 2)
    assert door.position.x == pytest.approx(-0.55, abs=0.03)
    assert (door.size.x, door.size.z) == pytest.approx((0.9, 2.1), abs=0.03)
    wide = CameraRig(
        position=Vec3(y=-2.0, z=1.6), target=Vec3(y=3.0, z=1.6), lens_mm=14.0
    )
    win_face = [Vec3(x=-4.0, y=y, z=z) for y in (2.0, 3.0) for z in (1.0, 2.0)]
    window = place_opening(
        _ROOM,
        master_camera(_ROOM, rig=wide),
        OpeningObs(kind="window", wall="left", box_2d=_box_2d(_bbox(wide, win_face))),
        "w",
        "Window",
    )
    assert window.rotation_z_deg == 90.0
    assert window.position.x == pytest.approx(-4.0 + THICK / 2)
    assert window.position.y == pytest.approx(2.5, abs=0.05)
    assert window.params["sill_z"] == pytest.approx(1.0, abs=0.05)
    assert window.size.z == pytest.approx(1.0, abs=0.05)


def test_described_door_is_added_when_the_vlm_missed_it() -> None:
    cam = master_camera(_ROOM)
    added = place_openings("loc", _ROOM, cam, [], "A workshop with a heavy door.")
    assert [(p.kind, p.entity_id) for p in added] == [("door", "loc__door_1")]
    assert added[0].position.y == pytest.approx(_ROOM.depth - THICK / 2)
    seen = [OpeningObs(kind="door", wall="right")]
    assert len(place_openings("loc", _ROOM, cam, seen, "a door")) == 1  # no duplicate


def test_piece_drawn_on_another_stands_on_top_of_it() -> None:
    req = LayoutRequest(
        location_id="loc",
        name="Workshop",
        set_pieces=(
            ObjectInput(entity_id="obj_bench", name="Workbench"),
            ObjectInput(entity_id="obj_tools", name="Red Toolbox"),
        ),
    )
    obs = LayoutObs(
        pieces=[
            PieceObs(name="Workbench", box_2d=[520, 100, 860, 400]),
            PieceObs(name="Red Toolbox", box_2d=[430, 150, 560, 250]),
        ]
    )
    pieces = {p.entity_id: p for p in build_layout(req, obs).set_pieces}
    bench, tools = pieces["obj_bench"], pieces["obj_tools"]
    assert (bench.kind, tools.kind) == ("bench", "toolbox")
    assert bench.position.z == 0.0
    assert tools.position.z == pytest.approx(bench.size.z)
    assert tools.position.y == bench.position.y
    assert abs(tools.position.x - bench.position.x) <= (bench.size.x - tools.size.x) / 2
    assert tools.size.z < bench.size.z  # measured above the worktop, not from the floor

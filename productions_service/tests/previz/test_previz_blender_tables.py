"""Pure Blender-script tables: part kinds, room shell, rigs, motion, projection maths, IDs."""

from __future__ import annotations

import math

import pytest
from storygraph.previz.render.blender import motion, palette, parts, projmath, rigs

EPS = 1e-9


def _bounds(table: list[parts.Part]) -> tuple[list[float], list[float]]:
    lo, hi = [math.inf] * 3, [-math.inf] * 3
    for _name, _shape, centre, size, _tone in table:
        for i in range(3):
            lo[i] = min(lo[i], centre[i] - size[i] / 2)
            hi[i] = max(hi[i], centre[i] + size[i] / 2)
    return lo, hi


@pytest.mark.parametrize(
    ("kind", "params", "count"),
    [
        ("cabinet", {"drawers": 4}, 9), ("chest", {}, 2), ("bench", {}, 5), ("table", {}, 5),
        ("shelf", {"shelves": 5}, 8), ("stool", {"legs": 3}, 4), ("stool", {}, 5), ("door", {}, 5),
        ("window", {"sill_z": 1.1}, 7), ("toolbox", {}, 4), ("spaceship", {}, 1), ("box", {}, 1),
    ],
)  # fmt: skip
def test_kind_part_counts_and_parts_stay_inside_size(
    kind: str, params: dict[str, float], count: int
) -> None:
    w, d, h = 1.2, 0.5, 0.9
    table = parts.piece_parts(kind, (w, d, h), params)
    assert len(table) == count
    z0 = params.get("sill_z", 0.0) if kind == "window" else 0.0
    lo, hi = _bounds(table)
    assert lo[0] >= -w / 2 - EPS and hi[0] <= w / 2 + EPS
    assert lo[1] >= -d / 2 - EPS and hi[1] <= d / 2 + EPS
    assert lo[2] >= z0 - EPS and hi[2] <= z0 + h + EPS
    assert hi[2] == pytest.approx(z0 + h)  # the silhouette reaches the full height


def test_legacy_cylinder_shape_and_unknown_kind_fallbacks() -> None:
    assert [p[1] for p in parts.piece_parts("box", (1, 1, 1), shape="cylinder")] == [
        "cylinder"
    ]
    assert parts.piece_parts("rocket", (1, 2, 3)) == parts.piece_parts("box", (1, 2, 3))


def test_apron_reaches_camera_side_and_sits_below_floor() -> None:
    slabs = {
        name: (centre, size)
        for name, _role, centre, size, _tone in parts.room_slabs(8.0, 6.0, 3.0)
    }
    (cy, cz), (sy, sz) = slabs["apron"][0][1:], slabs["apron"][1][1:]
    floor_top = slabs["floor"][0][2] + slabs["floor"][1][2] / 2
    assert cy - sy / 2 == pytest.approx(-8.0)  # apron starts 8 m in front of the room
    assert cy + sy / 2 > 6.0  # and runs under the back wall: no gap at the room edge
    assert cz + sz / 2 < floor_top  # never z-fights / covers the room floor


@pytest.mark.parametrize("archetype", ["human", "small_robot", "quadruped", "creature"])
def test_rigs_are_well_formed_unit_height(archetype: str) -> None:
    joints, rig_parts = rigs.rig_for(archetype)
    defined = {"root"}
    for name, parent, _pivot in joints:
        assert parent in defined, f"{name} before its parent {parent}"
        defined.add(name)
    assert {"body", "hand_r"} <= defined
    assert all(node in defined for _n, _s, node, *_rest in rig_parts)
    top = max(_part_top(joints, p) for p in rig_parts)
    assert 0.85 <= top <= 1.02  # root scale == height_m gives the requested height


def _part_top(joints: list[rigs.Joint], part: rigs.RigPart) -> float:
    pivots = {name: (parent, pivot) for name, parent, pivot in joints}
    z, node = part[3][2] + part[4][2] / 2, part[2]
    while node in pivots:
        node, pivot = pivots[node][0], pivots[node][1]
        z += pivot[2]
    return z


def test_rig_limbs_per_archetype() -> None:
    legs = {
        a: sum(1 for p in rigs.rig_for(a)[1] if p[0].startswith("leg_"))
        for a in rigs.ARCHETYPES
    }
    assert legs == {"human": 2, "small_robot": 2, "quadruped": 4, "creature": 0}


def _walk(speed: float, archetype: str = "human") -> list[motion.MotionSample]:
    keys = [{"t": 0.0, "pose": "walk", "position": {"x": 0.0, "y": 0.0}},
            {"t": 2.0, "pose": "walk", "position": {"x": 2.0 * speed, "y": 0.0}}]  # fmt: skip
    return motion.sample_motion(archetype, 1.6, keys, 2.0)


def test_walk_swing_grows_with_speed_and_never_freezes() -> None:
    def swing(samples: list[motion.MotionSample]) -> float:
        return max(abs(s.pose.joints.get("hip_l", 0.0)) for s in samples)

    assert swing(_walk(1.4)) > swing(_walk(0.4)) > 0.0
    assert swing(_walk(0.0)) > 0.0  # walking on the spot still animates


def test_quadruped_gait_moves_diagonal_legs_together() -> None:
    for sample in _walk(1.0, "quadruped"):
        j = sample.pose.joints
        assert j["hip_fl"] == pytest.approx(j["hip_br"]) and j[
            "hip_fr"
        ] == pytest.approx(j["hip_bl"])
        assert j["hip_fl"] == pytest.approx(-j["hip_fr"])


def test_pose_change_blends_instead_of_snapping() -> None:
    keys = [{"t": 0.0, "pose": "stand"}, {"t": 1.0, "pose": "push"}]
    by_t = {
        round(s.t, 3): s.pose for s in motion.sample_motion("human", 1.6, keys, 2.0)
    }
    assert by_t[1.0].lean == pytest.approx(0.0)
    assert 0.0 < by_t[1.125].lean < 14.0
    assert by_t[1.5].lean == pytest.approx(14.0) and by_t[1.5].joints[
        "shoulder_r"
    ] == pytest.approx(-85.0)


def test_reach_aims_at_target_height() -> None:
    high = motion.reach_angle(1.3, (0.0, 0.0), (0.0, -0.5, 2.0))
    low = motion.reach_angle(1.3, (0.0, 0.0), (0.0, -0.5, 0.3))
    assert high > 90.0 > low >= 30.0
    assert motion.reach_angle(1.3, (0.0, 0.0), None) == 75.0


def _rig(**extra: float) -> dict[str, object]:
    return {
        "position": {"x": 0, "y": -4, "z": 1.5},
        "target": {"x": 0, "y": 6, "z": 1.5},
        "lens_mm": 36.0,
        **extra,
    }


def test_projection_centre_edge_shift_and_roll() -> None:
    cam = projmath.make_pinhole(_rig(), 16 / 9)
    assert projmath.project(cam, (0.0, 6.0, 1.5))[:2] == pytest.approx((0.5, 0.5))
    # Horizontal fit: 36 mm sensor / 36 mm lens -> frame half-width = 0.5 * depth.
    assert projmath.project(cam, (5.0, 6.0, 1.5))[0] == pytest.approx(1.0)
    assert projmath.project(cam, (0.0, 6.0, 1.5 + 5.0 * 9 / 16))[1] == pytest.approx(
        1.0
    )
    shifted = projmath.make_pinhole(_rig(shift_x=0.1, shift_y=0.05), 16 / 9)
    assert projmath.project(shifted, (0.0, 6.0, 1.5))[:2] == pytest.approx(
        (0.4, 0.5 - 0.05 * 16 / 9)
    )
    rolled = projmath.make_pinhole(_rig(roll_deg=90.0), 16 / 9)
    u, v, _ = projmath.project(
        rolled, (1.0, 6.0, 1.5)
    )  # +X point: rolled camera sees it "down"
    assert u == pytest.approx(0.5) and v < 0.5
    assert projmath.project(cam, (0.0, -10.0, 1.5))[2] < 0  # behind the projector


def test_id_colors_unique_non_black_deterministic() -> None:
    ids = [f"e{i}" for i in range(300)]
    colors = palette.id_colors(ids)
    assert len(set(colors.values())) == 300 and (0, 0, 0) not in colors.values()
    assert colors == palette.id_colors(ids)


@pytest.mark.parametrize(
    ("color", "role", "expected"),
    [("#b08060", 0.8, "#8d664d"), ("#ffffff", 2.0, "#ffffff"), ("not-a-color", 1.0, "not-a-color"),
     ("not-a-color", 0.5, "#444444"), ("#123456", "dark", "#202020")],
)  # fmt: skip
def test_tone_scales_clamps_and_falls_back(
    color: str, role: float | str, expected: str
) -> None:
    assert palette.tone(color, role) == expected


@pytest.mark.parametrize(
    ("headings", "expected"),
    [
        ([170.0, -170.0], [170.0, 190.0]),
        ([0.0, 270.0, 0.0], [0.0, -90.0, 0.0]),
        ([350.0, 10.0, 30.0], [350.0, 370.0, 390.0]),
    ],
)
def test_unwrap_angles_turns_the_short_way(
    headings: list[float], expected: list[float]
) -> None:
    assert motion.unwrap_angles(headings) == pytest.approx(expected)

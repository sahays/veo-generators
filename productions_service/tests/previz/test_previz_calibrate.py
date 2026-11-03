"""Plate camera calibration: recovers a known camera from a synthetic room, edge metrics,
degenerate-input fallback."""

from __future__ import annotations

import io
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw
from storygraph.previz.camera.calibrate import (
    Calibration,
    calibrate_from_obs,
    calibrate_plate,
)
from storygraph.previz.camera.edges import edge_iou, edge_scores
from storygraph.previz.camera.geometry import (
    Floats,
    Frame,
    corner_points,
    params,
    project,
)
from storygraph.previz.camera.observe import CORNER_FIELDS, ImagePoint, RoomCornersObs
from storygraph.schemas.previz_scene import Room

FRAME = Frame(960, 540)
TRUE = params(
    cam_x=0.2, cam_y=-5.0, cam_h=1.5, pitch=math.radians(-6.0), focal=0.75,
    width=5.0, depth=5.0, height=3.0,
)  # fmt: skip
FACES = {  # polygon corners + grey level: floor, back wall, side walls
    "floor": (("front_bl", "front_br", "back_br", "back_bl"), 150),
    "back": (("back_bl", "back_br", "back_tr", "back_tl"), 215),
    "left": (("front_bl", "back_bl", "back_tl", "front_tl"), 185),
    "right": (("front_br", "back_br", "back_tr", "front_tr"), 175),
}


def _px(v: Floats) -> dict[str, tuple[float, float]]:
    corners = corner_points(v)
    names = list(corners)
    pts = project(v, np.stack([corners[n] for n in names]), FRAME)
    return {n: (float(p[0]), float(p[1])) for n, p in zip(names, pts, strict=True)}


def _room_png(v: Floats, shift_px: int = 0) -> bytes:
    """Flat-shaded room box drawn with PIL from the pinhole camera `v`."""
    img = Image.new("L", (FRAME.width, FRAME.height), 40)
    draw = ImageDraw.Draw(img)
    px = _px(v)
    for names, grey in FACES.values():
        draw.polygon([(px[n][0] + shift_px, px[n][1]) for n in names], fill=grey)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def _obs(v: Floats, jitter_px: float = 0.0) -> RoomCornersObs:
    """What a VLM would report: corners (optionally jittered deterministically)."""
    px = _px(v)
    rng = np.random.default_rng(7)
    points = {}
    for field, corner in CORNER_FIELDS.items():
        du, dv = rng.uniform(-jitter_px, jitter_px, 2)
        u, w = px[corner]
        points[field] = ImagePoint(x=(u + du) / FRAME.width, y=(w + dv) / FRAME.height)
    # Scale priors off by ~6% in opposite directions: geometry fixes the shape, the priors
    # only the metric scale, so the fit lands near the truth rather than on any one guess.
    return RoomCornersObs(
        **points,
        eye_height_m=1.6,
        room_width_m=4.7,
        room_depth_m=5.0,
        room_height_m=3.0,
    )


def _recovered(png: bytes, obs: RoomCornersObs) -> Calibration:
    """Calibrate and check pitch / FOV / eye height / room size / yaw against TRUE."""
    calib = calibrate_from_obs(png, obs)
    assert calib.fallback_reason is None
    assert calib.pitch_deg == pytest.approx(-6.0, abs=0.5)
    assert calib.hfov_deg == pytest.approx(
        2 * math.degrees(math.atan(1 / 1.5)), abs=1.0
    )
    assert calib.rig.position.z == pytest.approx(1.5, rel=0.06)
    assert calib.room.width == pytest.approx(5.0, rel=0.06)
    assert calib.room.depth == pytest.approx(5.0, rel=0.1)
    assert calib.rig.target.x == pytest.approx(calib.rig.position.x, abs=0.15)  # no yaw
    return calib


def test_calibrate_recovers_known_camera_from_exact_corners() -> None:
    calib = _recovered(_room_png(TRUE), _obs(TRUE))
    assert calib.corner_rms_px < 3.0
    assert calib.horizon_y_px is not None


def test_line_snapping_corrects_noisy_vlm_corners() -> None:
    """VLM corners off by up to 2.5% of the width: the plate's own edges pull the fit back."""
    calib = _recovered(_room_png(TRUE), _obs(TRUE, jitter_px=24.0))
    assert calib.n_line_obs >= 6
    assert calib.line_rms_px < 2.0


def test_calibrated_camera_reprojects_onto_drawn_box() -> None:
    calib = calibrate_from_obs(_room_png(TRUE), _obs(TRUE, jitter_px=24.0))
    truth = _px(TRUE)
    worst = max(
        math.dist(calib.corners_px[c], truth[c])
        for c in ("back_bl", "back_br", "back_tl", "back_tr")
    )
    assert worst < 4.0


def test_blank_plate_falls_back_to_default_master_camera() -> None:
    blank = io.BytesIO()
    Image.new("RGB", (FRAME.width, FRAME.height), (128, 128, 128)).save(blank, "PNG")
    calib = calibrate_from_obs(blank.getvalue(), RoomCornersObs())
    assert (
        calib.fallback_reason is not None and "straight edges" in calib.fallback_reason
    )
    assert calib.room.width == Room().width
    assert calib.rig.lens_mm == pytest.approx(35.0)


def test_too_few_vlm_corners_falls_back() -> None:
    obs = _obs(TRUE).model_copy(
        update={f: None for f in CORNER_FIELDS if f != "back_top_left"}
    )
    calib = calibrate_from_obs(_room_png(TRUE), obs)
    assert calib.fallback_reason is not None and "corners" in calib.fallback_reason


class _BrokenVLM:
    def review(self, images: list[bytes], prompt: str, schema: type) -> object:
        raise RuntimeError("quota exhausted")


def test_vlm_failure_falls_back_with_reason() -> None:
    calib = calibrate_plate(_room_png(TRUE), _BrokenVLM())
    assert calib.fallback_reason is not None and "quota" in calib.fallback_reason


def test_edge_iou_identical_shifted_and_symmetric() -> None:
    a, near, far = _room_png(TRUE), _room_png(TRUE, 6), _room_png(TRUE, 40)
    assert edge_iou(a, a) == pytest.approx(1.0)
    assert edge_iou(a, far) < edge_iou(a, near) < 1.0
    assert edge_iou(a, far) == pytest.approx(edge_iou(far, a), abs=0.05)


def test_edge_scores_chamfer_grows_with_misalignment() -> None:
    a = _room_png(TRUE)
    same, near, far = (
        edge_scores(a, a),
        edge_scores(a, _room_png(TRUE, 6)),
        edge_scores(a, _room_png(TRUE, 40)),
    )
    assert same.chamfer_px == 0.0 and same.precision == 1.0 and same.recall == 1.0
    assert same.chamfer_px < near.chamfer_px < far.chamfer_px

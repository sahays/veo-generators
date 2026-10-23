"""Deterministic drift guard against the scene plate (synthetic images, no VLM)."""

from __future__ import annotations

import io

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from storygraph.keyframes.render.drift import DriftCfg, check_drift

W, H = 640, 360
CABINET = (slice(int(0.3 * H), int(0.9 * H)), slice(int(0.05 * W), int(0.2 * W)))
_CFG = DriftCfg()


def _room() -> NDArray[np.float64]:
    """Warm horizontal gradient room with a saturated blue cabinet at x 0.05..0.2."""
    t = np.linspace(0.0, 1.0, W)[None, :, None]
    left, right = np.array([220.0, 140.0, 60.0]), np.array([170.0, 110.0, 50.0])
    img = np.broadcast_to(left + (right - left) * t, (H, W, 3)).copy()
    img[CABINET] = (30.0, 60.0, 200.0)
    return img


def _png(img: NDArray[np.float64]) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def _grey_cabinet() -> NDArray[np.float64]:
    img = _room()
    img[CABINET] = (110.0, 110.0, 110.0)
    return img


PLATE = _png(_room())


def test_identical_frame_is_clean() -> None:
    report = check_drift(PLATE, PLATE, [], _CFG)
    assert report.ok and report.bad_fraction == 0.0


def test_recoloured_cabinet_is_background_drift() -> None:
    report = check_drift(PLATE, _png(_grey_cabinet()), [0.8], _CFG)
    assert not report.ok
    assert "static background changed" in report.reason


def test_same_change_inside_a_character_band_is_masked() -> None:
    """A character standing in front of the cabinet legitimately covers it."""
    report = check_drift(PLATE, _png(_grey_cabinet()), [0.125], _CFG)
    assert report.ok, report.reason


def test_global_desaturation_fails_chroma() -> None:
    img = _room()
    grey = img.mean(axis=-1, keepdims=True)
    report = check_drift(PLATE, _png(grey + 0.4 * (img - grey)), [], _CFG)
    assert not report.ok and "saturation" in report.reason
    assert report.chroma_ratio < 1 / _CFG.max_ratio


def test_per_pixel_grain_averages_out() -> None:
    rng = np.random.default_rng(3)
    noisy = _room() + rng.normal(0.0, 15.0, (H, W, 3))
    report = check_drift(PLATE, _png(noisy), [], _CFG)
    assert report.ok, report.reason


def test_undecodable_frame_is_unmeasurable_not_fatal() -> None:
    report = check_drift(PLATE, b"not a png", [], _CFG)
    assert report.ok and report.reason.startswith("unmeasurable")

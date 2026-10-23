"""Deterministic drift guard: compare a keyframe's static regions with the scene plate (no VLM).

Both images are box-downsampled to a 64x36 grid (grain/noise averages out) and converted to
CIE Lab. Columns where characters stand at this second (their x ± `band`) are masked out —
everything else must still look like the plate. Rejection if any holds:
* `bad_fraction`: share of static cells with ΔE76 > `cell_delta_e` exceeds `max_bad_fraction`
  (a blue cabinet turning grey, a door toggling, furniture moving);
* `chroma_ratio` / `contrast_ratio`: static-cell mean chroma or L std drift outside
  [1/`max_ratio`, `max_ratio`] (cumulative saturation / contrast / grain build-up).
O(grid) per frame; pure given the two PNGs.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

GRID = (64, 36)
Lab = NDArray[np.float64]


@dataclass(frozen=True)
class DriftCfg:
    band: float = 0.12
    cell_delta_e: float = 25.0
    max_bad_fraction: float = 0.04
    max_ratio: float = 1.25


@dataclass(frozen=True)
class DriftReport:
    bad_fraction: float
    chroma_ratio: float
    contrast_ratio: float
    ok: bool
    reason: str = ""


def _lab(png: bytes) -> Lab:
    img = Image.open(io.BytesIO(png)).convert("RGB").resize(GRID, Image.Resampling.BOX)
    rgb = np.asarray(img, dtype=np.float64) / 255.0
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = (
        lin
        @ np.array(
            [
                [0.4124, 0.3576, 0.1805],
                [0.2126, 0.7152, 0.0722],
                [0.0193, 0.1192, 0.9505],
            ]
        ).T
    )
    xyz /= np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack(
        [
            116 * f[..., 1] - 16,
            500 * (f[..., 0] - f[..., 1]),
            200 * (f[..., 1] - f[..., 2]),
        ],
        axis=-1,
    )


def static_mask(character_x: Sequence[float], band: float) -> NDArray[np.bool_]:
    """True for grid columns no character occupies at this second."""
    cols = (np.arange(GRID[0]) + 0.5) / GRID[0]
    mask = np.ones(GRID[0], dtype=bool)
    for x in character_x:
        mask &= np.abs(cols - x) > band
    return np.broadcast_to(mask, (GRID[1], GRID[0]))


def _ratio(a: float, b: float) -> float:
    return float(a / b) if b > 1e-6 else 1.0


def _global_ratios(plate: Lab, frame: Lab) -> tuple[float, float]:
    """(chroma, contrast) ratios frame/plate over the given (static) cells, shape (N, 3)."""
    if not len(plate):
        return 1.0, 1.0
    chroma = _ratio(
        np.hypot(frame[:, 1], frame[:, 2]).mean(),
        np.hypot(plate[:, 1], plate[:, 2]).mean(),
    )
    return chroma, _ratio(frame[:, 0].std(), plate[:, 0].std())


def measure(
    plate_png: bytes, frame_png: bytes, character_x: Sequence[float], cfg: DriftCfg
) -> DriftReport:
    """All statistics on static (unoccupied) cells only: characters never count as drift."""
    plate, frame = _lab(plate_png), _lab(frame_png)
    mask = static_mask(character_x, cfg.band)
    ps, fs = plate[mask], frame[mask]
    delta = np.linalg.norm(ps - fs, axis=-1)
    bad = float(np.mean(delta > cfg.cell_delta_e)) if delta.size else 0.0
    chroma, contrast = _global_ratios(ps, fs)
    lo, hi = 1 / cfg.max_ratio, cfg.max_ratio
    reasons = [
        f"static background changed in {bad:.0%} of the frame"
        if bad > cfg.max_bad_fraction
        else "",
        f"colour saturation drifted x{chroma:.2f}" if not lo <= chroma <= hi else "",
        f"contrast drifted x{contrast:.2f}" if not lo <= contrast <= hi else "",
    ]
    reason = "; ".join(r for r in reasons if r)
    return DriftReport(
        round(bad, 4), round(chroma, 3), round(contrast, 3), not reason, reason
    )


def check_drift(
    plate_png: bytes, frame_png: bytes, character_x: Sequence[float], cfg: DriftCfg
) -> DriftReport:
    """`measure`, treating undecodable images as unmeasurable (ok, reason recorded)."""
    try:
        return measure(plate_png, frame_png, character_x, cfg)
    except (OSError, ValueError) as exc:
        return DriftReport(0.0, 1.0, 1.0, True, f"unmeasurable: {exc}")

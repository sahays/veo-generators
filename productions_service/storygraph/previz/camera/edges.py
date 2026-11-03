"""Edge maps and edge-alignment metrics between two images (pure numpy + PIL, O(pixels)).

`edge_map` = Gaussian blur -> Sobel -> non-maximum suppression -> adaptive threshold (90th
percentile of the gradient magnitude, never below `ABS_MIN`), so a flat render and a textured
plate both yield thin structural edges. `edge_iou` compares two images by the IoU of their
dilated edge maps (symmetric; 1.0 for identical images, lower as edges drift apart);
`edge_scores` adds directional precision/recall and a truncated chamfer distance.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageFilter

Gray = NDArray[np.float32]
Mask = NDArray[np.bool_]
ANALYSIS_WIDTH: Final[int] = 480
BLUR_SIGMA: Final[float] = 1.2
ABS_MIN: Final[float] = 0.02  # min gradient (intensity units / px) of a kept edge
KEEP_QUANTILE: Final[float] = 0.9
CHAMFER_MAX_PX: Final[int] = 16


@dataclass(frozen=True)
class EdgeScores:
    """`precision` = share of A's edges near B's, `recall` = share of B's near A's."""

    iou: float
    precision: float
    recall: float
    chamfer_px: float


def load_gray(
    png: bytes, width: int | None = ANALYSIS_WIDTH, size: tuple[int, int] | None = None
) -> Gray:
    """Blurred grayscale in [0, 1], resized to `size` (w, h) or to `width` (aspect kept)."""
    img = Image.open(io.BytesIO(png)).convert("L")
    if size is not None and img.size != size:
        img = img.resize(size, Image.Resampling.BILINEAR)
    elif size is None and width and img.width != width:
        height = max(1, round(img.height * width / img.width))
        img = img.resize((width, height), Image.Resampling.BILINEAR)
    img = img.filter(ImageFilter.GaussianBlur(BLUR_SIGMA))
    return np.asarray(img, dtype=np.float32) / 255.0


def sobel(gray: Gray) -> tuple[Gray, Gray]:
    """(gx, gy) Sobel gradients normalised to intensity change per pixel."""
    p = np.pad(gray, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (
        p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2]
    )
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (
        p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:]
    )
    return (gx / 8).astype(np.float32), (gy / 8).astype(np.float32)


def _shift(a: Gray, dy: int, dx: int) -> Gray:
    """`a` shifted so out[y, x] = a[y + dy, x + dx] (edge-padded)."""
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    return p[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]


def thin_edges(gray: Gray) -> tuple[Mask, Gray, Gray]:
    """(edge mask, gx, gy): non-maximum-suppressed Sobel edges above the adaptive threshold."""
    gx, gy = sobel(gray)
    mag = np.hypot(gx, gy)
    angle = (np.degrees(np.arctan2(gy, gx)) + 180.0) % 180.0
    bins = ((angle + 22.5) // 45).astype(
        np.int8
    ) % 4  # 0: x, 1: diag, 2: y, 3: anti-diag
    keep = np.zeros(mag.shape, dtype=bool)
    for b, (dy, dx) in enumerate(((0, 1), (1, 1), (1, 0), (1, -1))):
        peak = (mag >= _shift(mag, dy, dx)) & (mag >= _shift(mag, -dy, -dx))
        keep |= (bins == b) & peak
    threshold = max(ABS_MIN, float(np.quantile(mag, KEEP_QUANTILE)))
    return keep & (mag > threshold), gx, gy


def edge_map(
    png: bytes, width: int | None = ANALYSIS_WIDTH, size: tuple[int, int] | None = None
) -> Mask:
    """Thin structural edge mask of a PNG/JPEG image (see module doc)."""
    return thin_edges(load_gray(png, width, size))[0]


def dilate(mask: Mask, radius: int) -> Mask:
    """Square (Chebyshev) dilation by `radius` px, separable: O(pixels * radius)."""
    out = mask.copy()
    for axis in (0, 1):
        src = out.copy()
        for s in range(1, radius + 1):
            if axis == 0:
                out[s:] |= src[:-s]
                out[:-s] |= src[s:]
            else:
                out[:, s:] |= src[:, :-s]
                out[:, :-s] |= src[:, s:]
    return out


def _pair(a_png: bytes, b_png: bytes) -> tuple[Mask, Mask]:
    """Edge maps of both images at A's analysis size (B resized onto A's frame)."""
    a = edge_map(a_png)
    b = edge_map(b_png, size=(a.shape[1], a.shape[0]))
    return a, b


def edge_iou(a_png: bytes, b_png: bytes, dilate_px: int = 3) -> float:
    """IoU of the two dilated edge maps (1.0 when both are edge-free)."""
    a, b = _pair(a_png, b_png)
    da, db = dilate(a, dilate_px), dilate(b, dilate_px)
    union = int((da | db).sum())
    return 1.0 if union == 0 else float((da & db).sum()) / union


def _mean_distance(src: Mask, dst: Mask, max_px: int) -> float:
    """Mean Chebyshev distance from `src` edge pixels to the nearest `dst` edge (truncated)."""
    if not src.any():
        return 0.0
    if not dst.any():
        return float(max_px)
    dist = np.full(src.shape, float(max_px), dtype=np.float32)
    grown = dst.copy()
    for r in range(max_px):
        dist[grown & (dist == max_px)] = r
        grown = dilate(grown, 1)
    return float(dist[src].mean())


def edge_scores(a_png: bytes, b_png: bytes, dilate_px: int = 3) -> EdgeScores:
    """IoU + directional precision/recall + symmetric truncated chamfer distance (px)."""
    a, b = _pair(a_png, b_png)
    da, db = dilate(a, dilate_px), dilate(b, dilate_px)
    union = int((da | db).sum())
    na, nb = int(a.sum()), int(b.sum())
    chamfer = (
        _mean_distance(a, b, CHAMFER_MAX_PX) + _mean_distance(b, a, CHAMFER_MAX_PX)
    ) / 2
    return EdgeScores(
        iou=1.0 if union == 0 else float((da & db).sum()) / union,
        precision=1.0 if na == 0 else float((a & db).sum()) / na,
        recall=1.0 if nb == 0 else float((b & da).sum()) / nb,
        chamfer_px=round(chamfer, 3),
    )

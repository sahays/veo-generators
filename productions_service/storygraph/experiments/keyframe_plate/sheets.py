"""Labelled contact sheets: one row per side (before / after) per shot, plus the plate."""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image

from ...adapters.media_frames import label_image
from .metrics import FrameIn, FrameMetric

TILE_W = 256
BG = (20, 20, 20)


def _tile(png: bytes, label: str) -> Image.Image:
    try:
        return Image.open(io.BytesIO(label_image(png, label, TILE_W))).convert("RGB")
    except (OSError, ValueError):
        return Image.new("RGB", (TILE_W, TILE_W * 9 // 16), BG)


def tile_label(side: str, frame: FrameIn, metric: FrameMetric) -> str:
    mark = {"approved": "OK", "needs_review": "REVIEW", "manual_edit": "EDIT"}.get(
        frame.status, frame.status
    )
    first = frame.issues[0][:48] if frame.issues else ""
    return f"{side} t{frame.t:02d} {mark} d={metric.bad_fraction:.2f} {first}"


def grid(rows: Sequence[Sequence[Image.Image]]) -> bytes:
    """Rows of tiles -> one JPEG (rows may differ in length)."""
    rows = [r for r in rows if r]
    if not rows:
        return b""
    cols = max(len(r) for r in rows)
    cell_h = max(t.height for r in rows for t in r)
    sheet = Image.new("RGB", (cols * TILE_W, len(rows) * cell_h), BG)
    for y, row in enumerate(rows):
        for x, tile in enumerate(row):
            sheet.paste(tile, (x * TILE_W, y * cell_h))
    buf = io.BytesIO()
    sheet.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def side_row(
    side: str, frames: Sequence[FrameIn], metrics: Sequence[FrameMetric]
) -> list[Image.Image]:
    return [
        _tile(f.png, tile_label(side, f, m))
        for f, m in zip(frames, metrics, strict=True)
    ]


def plate_tile(png: bytes, label: str) -> Image.Image:
    return _tile(png, label)

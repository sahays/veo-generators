"""Composite labelled reference board: every reference in ONE image (no refs dropped).

The image model accepts only a few input images, so all identity/prop sheets needed for a
keyframe are tiled into a single board, each tile captioned with the entity name (the prompt
refers to tiles by that name). Deterministic: same inputs -> same bytes.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from math import ceil

from PIL import Image

from ...adapters.media_frames import label_image

TILE_WIDTH = 320
MAX_COLS = 3


def _tile(label: str, png: bytes) -> Image.Image | None:
    try:
        return Image.open(io.BytesIO(label_image(png, label, TILE_WIDTH))).convert(
            "RGB"
        )
    except (OSError, ValueError):  # undecodable reference: skipped, never fatal
        return None


def compose_board(items: Sequence[tuple[str, bytes]]) -> tuple[bytes, list[str]]:
    """Grid of labelled tiles -> (PNG bytes, labels actually on the board); none -> (b"", [])."""
    pairs = [(label, _tile(label, png)) for label, png in items if png]
    kept = [(label, tile) for label, tile in pairs if tile is not None]
    if not kept:
        return b"", []
    tiles = [tile for _, tile in kept]
    cols = min(MAX_COLS, len(tiles))
    rows = ceil(len(tiles) / cols)
    cell_h = max(t.height for t in tiles)
    board = Image.new("RGB", (cols * TILE_WIDTH, rows * cell_h), (24, 24, 24))
    for i, tile in enumerate(tiles):
        board.paste(tile, ((i % cols) * TILE_WIDTH, (i // cols) * cell_h))
    buf = io.BytesIO()
    board.save(buf, format="PNG")
    return buf.getvalue(), [label for label, _ in kept]

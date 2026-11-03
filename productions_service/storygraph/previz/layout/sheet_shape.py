"""Subject proportions of a reference sheet (pure, deterministic, O(pixels)).

Real sheets are cluttered dioramas (desk, tools, clay crumbs, labels), so "not the border
background" marks nearly everything as foreground. The subject is keyed by its own colour
instead: foreground = pixels within KEY_DIST of the sheet's subject colour
(`sheet_color.subject_color`) and not close to a border-ring background colour. Sheets are
often turnarounds (front / 3/4 / back views side by side), so the foreground column profile
is split into runs separated by empty columns and the run holding the most foreground
pixels is the subject view; its row extent (also split on empty rows, largest run) gives
the box. Width / height of that box is the object's front aspect ratio. Thin noise (< 2 %
of the side) never counts, and a box spanning (almost) the whole sheet is rejected as
unreliable (None) so the kind's default proportions are used instead.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from .sheet_color import Rgb, Sheet, background, load_sheet, near_any, subject_color

NOISE: Final[float] = 0.02
GAP: Final[int] = 2  # empty columns/rows that separate two views
KEY_DIST: Final[int] = 64  # RGB distance to the subject colour (shading tolerance)
FULL: Final[float] = 0.95  # a box this wide AND tall is the whole sheet: unreliable
Run = tuple[int, int, int]  # (start, end exclusive, foreground pixels)


def foreground_mask(sheet: Sheet, key: Rgb) -> list[bool]:
    """Pixels of the subject's colour that are not background."""
    bg = background(sheet)
    limit = KEY_DIST**2
    return [
        sum((a - b) ** 2 for a, b in zip(p, key, strict=True)) < limit
        and not near_any(p, bg)
        for p in sheet.pixels
    ]


def _runs(counts: Sequence[int], floor: int) -> list[Run]:
    """Maximal runs of `counts > floor`, bridging gaps shorter than GAP."""
    runs: list[Run] = []
    start, last, total = -1, -GAP - 1, 0
    for i, c in enumerate(counts):
        if c <= floor:
            continue
        if start >= 0 and i - last > GAP:
            runs.append((start, last + 1, total))
            start, total = -1, 0
        start = i if start < 0 else start
        last, total = i, total + c
    if start >= 0:
        runs.append((start, last + 1, total))
    return runs


def _largest(runs: list[Run]) -> Run | None:
    return max(runs, key=lambda r: (r[2], -r[0])) if runs else None


def subject_bbox(sheet: Sheet) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) pixel box of the largest subject-coloured view (None: none)."""
    key = subject_color(sheet)
    if key is None:
        return None
    mask, w, h = foreground_mask(sheet, key), sheet.width, sheet.height
    cols = [sum(mask[y * w + x] for y in range(h)) for x in range(w)]
    col = _largest(_runs(cols, round(NOISE * h)))
    if col is None:
        return None
    x0, x1, _ = col
    rows = [sum(mask[y * w + x] for x in range(x0, x1)) for y in range(h)]
    row = _largest(_runs(rows, round(NOISE * (x1 - x0))))
    return None if row is None else (x0, row[0], x1, row[1])


def sheet_aspect(sheet: Sheet) -> float | None:
    """Width / height of the decoded sheet's subject view (None: blank / unreliable)."""
    box = subject_bbox(sheet)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    if x1 - x0 >= FULL * sheet.width and y1 - y0 >= FULL * sheet.height:
        return None
    return round((x1 - x0) / max(y1 - y0, 1), 3)


def subject_aspect(png: bytes) -> float | None:
    """Width / height of the sheet's subject view (None: undecodable or blank)."""
    sheet = load_sheet(png)
    return sheet_aspect(sheet) if sheet else None

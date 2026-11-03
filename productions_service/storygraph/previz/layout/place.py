"""Deterministic set-piece placement fix-up: clamp into the room, push overlaps apart on X.

Pieces are processed in (X, entity id) order. A forward sweep moves each piece right of
every earlier piece it would intersect (footprints overlapping in depth); a backward sweep
from the right wall moves pieces left of later pieces and the wall. Depth (Y) never changes,
so the plate's near/far ordering is preserved. O(n^2) in the number of set pieces (tens).
"""

from __future__ import annotations

from typing import Final

from ...schemas.previz_scene import Room, SetPiece

GAP: Final[float] = 0.1
WALL: Final[float] = 0.05


def _depth_overlap(a: SetPiece, b: SetPiece) -> bool:
    return abs(a.position.y - b.position.y) < (a.size.y + b.size.y) / 2 + GAP


def _with_x(piece: SetPiece, x: float) -> SetPiece:
    pos = piece.position.model_copy(update={"x": round(x, 3)})
    return piece.model_copy(update={"position": pos})


def _forward(pieces: list[SetPiece], left: float) -> list[SetPiece]:
    out: list[SetPiece] = []
    for p in pieces:
        x = max(p.position.x, left + p.size.x / 2)
        for q in out:
            if _depth_overlap(p, q):
                x = max(x, q.position.x + (p.size.x + q.size.x) / 2 + GAP)
        out.append(_with_x(p, x))
    return out


def _backward(pieces: list[SetPiece], right: float) -> list[SetPiece]:
    out: list[SetPiece] = []
    for p in reversed(pieces):
        x = min(p.position.x, right - p.size.x / 2)
        for q in out:
            if _depth_overlap(p, q):
                x = min(x, q.position.x - (p.size.x + q.size.x) / 2 - GAP)
        out.append(_with_x(p, x))
    return out[::-1]


def resolve_overlaps(pieces: list[SetPiece], room: Room) -> list[SetPiece]:
    """Clamped, non-overlapping pieces sorted by entity id (stable output order)."""
    half = room.width / 2 - WALL
    ordered = sorted(pieces, key=lambda p: (p.position.x, p.entity_id))
    placed = _backward(_forward(ordered, -half), half)
    return sorted(placed, key=lambda p: p.entity_id)

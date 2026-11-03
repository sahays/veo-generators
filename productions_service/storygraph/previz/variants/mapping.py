"""Colour mapping between greybox mannequins/primitives and story entities (pure).

Every greybox element is coloured with its entity's dominant reference colour, so the
restyle prompts can say "the yellow mannequin is Ava". Names come from the nearest entry of a
small fixed palette in RGB (deterministic, no model).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ...schemas.previz_scene import PrevizScene

PALETTE: Final[dict[str, tuple[int, int, int]]] = {
    "red": (200, 40, 40),
    "orange": (230, 130, 30),
    "yellow": (230, 200, 40),
    "green": (60, 160, 70),
    "teal": (40, 150, 150),
    "blue": (50, 90, 200),
    "purple": (130, 60, 170),
    "pink": (230, 130, 170),
    "brown": (130, 80, 40),
    "tan": (200, 170, 120),
    "white": (235, 235, 235),
    "grey": (128, 128, 128),
    "black": (25, 25, 25),
}


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return PALETTE["grey"]
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return PALETTE["grey"]


def colour_word(hex_color: str) -> str:
    r, g, b = _rgb(hex_color)
    return min(
        PALETTE,
        key=lambda n: sum(
            (a - c) ** 2 for a, c in zip(PALETTE[n], (r, g, b), strict=True)
        ),
    )


@dataclass(frozen=True)
class Mapped:
    entity_id: str
    name: str
    colour: str  # palette word
    kind: str  # "mannequin" | "box" | "cylinder" | "prop"


def colour_map(scene: PrevizScene) -> list[Mapped]:
    """Every coloured greybox element of `scene` with the entity it stands for."""
    out = [
        Mapped(c.entity_id, c.name, colour_word(c.color), "mannequin")
        for c in scene.blocking.characters
    ]
    out += [
        Mapped(p.entity_id, p.name, colour_word(p.color), p.shape)
        for p in scene.layout.set_pieces
    ]
    out += [
        Mapped(p.entity_id, p.name, colour_word(p.color), "prop")
        for p in scene.blocking.props
    ]
    return out


def mapping_lines(mapped: list[Mapped]) -> list[str]:
    return [f"- the {m.colour} {m.kind} is {m.name}" for m in mapped]

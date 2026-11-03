"""Pure colour helpers: hex parsing, tones, sRGB->linear, and exact object-ID colours."""

from __future__ import annotations

import colorsys

RGB = tuple[float, float, float]
RGB8 = tuple[int, int, int]
GOLDEN = 0.618033988749895
FALLBACK_RGB: RGB = (0.533, 0.533, 0.533)
ROLE_COLORS: dict[str, str] = {"dark": "#202020", "light": "#f2f2f2"}


def parse_hex(color: str) -> RGB:
    """'#rrggbb' -> sRGB channels in [0, 1]; malformed input falls back to mid grey."""
    raw = color.lstrip("#")
    if len(raw) != 6:
        return FALLBACK_RGB
    try:
        return (
            int(raw[0:2], 16) / 255.0,
            int(raw[2:4], 16) / 255.0,
            int(raw[4:6], 16) / 255.0,
        )
    except ValueError:
        return FALLBACK_RGB


def to_hex(rgb: RGB) -> str:
    """sRGB channels (clamped to [0, 1]) -> '#rrggbb'."""
    return "#" + "".join(f"{round(min(max(c, 0.0), 1.0) * 255):02x}" for c in rgb)


def darken(color: str, factor: float) -> str:
    """Scale an sRGB hex colour's channels by `factor` (clamped); >1 lightens."""
    return to_hex(tuple(c * factor for c in parse_hex(color)))  # type: ignore[arg-type]


def tone(color: str, role: str | float) -> str:
    """Part colour: a fixed role colour ('dark'/'light') or the base scaled by a float tone."""
    if isinstance(role, str):
        return ROLE_COLORS.get(role, color)
    return color if role == 1.0 else darken(color, role)


def srgb_to_linear(c: float) -> float:
    """One sRGB channel -> linear (IEC 61966-2-1)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear(color: str) -> tuple[float, float, float, float]:
    """'#rrggbb' (sRGB) -> linear RGBA."""
    r, g, b = (srgb_to_linear(c) for c in parse_hex(color))
    return (r, g, b, 1.0)


def id_colors(entity_ids: list[str]) -> dict[str, RGB8]:
    """Deterministic, distinct, non-black 8-bit colours per entity (golden-ratio hue walk).

    Saturation/value alternate across 4 bands so neighbours differ strongly; any (rare)
    8-bit collision is resolved by nudging the hue, so the mapping is always injective.
    """
    out: dict[str, RGB8] = {}
    used: set[RGB8] = {(0, 0, 0)}
    for idx, entity_id in enumerate(entity_ids):
        hue = (idx * GOLDEN) % 1.0
        sat, val = (0.9, 1.0) if idx % 2 == 0 else (0.6, 0.8 if idx % 4 == 1 else 0.95)
        rgb = _hsv8(hue, sat, val)
        while rgb in used:
            hue = (hue + 0.0137) % 1.0
            rgb = _hsv8(hue, sat, val)
        used.add(rgb)
        out[entity_id] = rgb
    return out


def _hsv8(hue: float, sat: float, val: float) -> RGB8:
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    return (round(r * 255), round(g * 255), round(b * 255))

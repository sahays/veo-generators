"""Deterministic entity colours from reference sheets (pure, no clustering).

`dominant_color` reads the sheet's subject colour (`sheet_color`: background estimated from
the border ring, chroma- and centre-weighted histogram mode); undecodable or colourless
sheets fall back to a stable hash colour. `distinct_colors` keeps the characters of one
scene visually apart (CIE76 ΔE >= 20, clashes resolved by deterministic hue rotation).
"""

from __future__ import annotations

import colorsys
import hashlib
import logging
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from ...adapters.bounded_cache import BoundedCache
from .sheet_color import Rgb, load_sheet, subject_color
from .sheet_shape import sheet_aspect

_log = logging.getLogger(__name__)
MIN_DELTA_E: Final[float] = 20.0
HUE_STEP: Final[float] = 47.0
HUE_TRIES: Final[int] = 7


@dataclass(frozen=True)
class SheetInfo:
    color: str  # "" when the sheet has no subject colour
    aspect: float | None  # subject width / height


_CACHE: BoundedCache[SheetInfo] = BoundedCache(512)
_LOCK = threading.Lock()


def _hex(rgb: Rgb) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def hash_color(key: str | bytes) -> str:
    """Stable mid-saturation colour for `key` (fallback when a sheet gives no colour)."""
    raw = key if isinstance(key, bytes) else key.encode("utf-8")
    hue = int(hashlib.sha256(raw).hexdigest()[:8], 16) / 0xFFFFFFFF
    r, g, b = colorsys.hsv_to_rgb(hue, 0.55, 0.8)
    return _hex((round(r * 255), round(g * 255), round(b * 255)))


def dominant_color(png: bytes, key: str = "") -> str:
    """`#rrggbb` subject colour of a sheet (`sheet_color`); hash colour if none."""
    sheet = load_sheet(png)
    rgb = subject_color(sheet) if sheet else None
    return _hex(rgb) if rgb else hash_color(key or png)


def _lab(hex_color: str) -> tuple[float, float, float]:
    """sRGB hex -> CIE L*a*b* (D65)."""

    def lin(c: int) -> float:
        v = c / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(int(hex_color[i : i + 2], 16)) for i in (1, 3, 5))
    xyz = (
        (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047,
        0.2126 * r + 0.7152 * g + 0.0722 * b,
        (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883,
    )
    fx, fy, fz = (t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116 for t in xyz)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """CIE76 colour difference."""
    return math.dist(_lab(a), _lab(b))


def _rotated(hex_color: str, degrees: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    s, v = max(s, 0.45), max(v, 0.45)  # a grey cannot be told apart by hue alone
    rr, gg, bb = colorsys.hsv_to_rgb((h + degrees / 360) % 1.0, s, v)
    return _hex((round(rr * 255), round(gg * 255), round(bb * 255)))


def distinct_colors(
    colors: Mapping[str, str], ids: Sequence[str], min_delta: float = MIN_DELTA_E
) -> dict[str, str]:
    """Colours for `ids` (in order) with every pair ΔE >= `min_delta`: a clash is resolved
    by rotating the later entity's hue in fixed steps (deterministic)."""
    out: dict[str, str] = {}
    for eid in ids:
        color = color_for(colors, eid)
        for step in range(1, HUE_TRIES + 1):
            if all(delta_e(color, c) >= min_delta for c in out.values()):
                break
            color = _rotated(color_for(colors, eid), HUE_STEP * step)
        out[eid] = color
    return out


def entity_colors(
    fetch: Callable[[str], bytes], refs: Mapping[str, str | None]
) -> dict[str, str]:
    """`entity id -> colour` from each entity's reference sheet URI (hash colour if none).

    Colours are cached per URI process-wide (URIs are content-addressed sheet versions)."""
    out: dict[str, str] = {}
    for eid, uri in sorted(refs.items()):
        info = _uri_info(fetch, eid, uri) if uri else None
        out[eid] = info.color if info and info.color else hash_color(eid)
    return out


def entity_aspects(
    fetch: Callable[[str], bytes], refs: Mapping[str, str | None]
) -> dict[str, float]:
    """`entity id -> subject width/height` of each readable reference sheet (same cache)."""
    out: dict[str, float] = {}
    for eid, uri in sorted(refs.items()):
        info = _uri_info(fetch, eid, uri) if uri else None
        if info is not None and info.aspect is not None:
            out[eid] = info.aspect
    return out


def _uri_info(fetch: Callable[[str], bytes], eid: str, uri: str) -> SheetInfo | None:
    with _LOCK:
        hit = _CACHE.get(uri)
    if hit is not None:
        return hit
    png = _fetch(fetch, eid, uri)
    if not png:
        return None
    sheet = load_sheet(png)
    rgb = subject_color(sheet) if sheet else None
    info = SheetInfo(_hex(rgb) if rgb else "", sheet_aspect(sheet) if sheet else None)
    with _LOCK:
        _CACHE.put(uri, info)
    return info


def _fetch(fetch: Callable[[str], bytes], eid: str, uri: str) -> bytes:
    try:
        return fetch(uri)
    except Exception as exc:  # noqa: BLE001 - any blob failure degrades to a hash colour
        _log.warning(
            "reference sheet unavailable",
            extra={
                "who": "storygraph.previz",
                "where": "previz.layout.colors",
                "what": f"fetch {uri} for {eid} failed",
                "when": datetime.now(UTC).isoformat(),
                "why": str(exc)[:200],
                "how": "fall back to stable hash colour",
            },
        )
        return b""


def color_for(colors: Mapping[str, str], entity_id: str) -> str:
    """The entity's sheet colour, else its stable hash colour."""
    return colors.get(entity_id) or hash_color(entity_id)

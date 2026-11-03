"""Pure parametric part tables: set-piece / prop kinds and the room shell (no bpy).

A `Part` is (name, shape, centre, size, tone) in the piece's LOCAL frame: footprint centred
on the origin, front facing -Y (towards the master camera before `rotation_z_deg`), z up from
the floor. Every part lies inside the `size` box (walls-mounted windows: inside
[sill_z, sill_z + H]). Shapes: box | cylinder | sphere (unit primitives scaled by `size`).
`tone` is a float multiplier on the piece colour or a role ('dark'/'light').
"""

from __future__ import annotations

import math
from collections.abc import Callable

Vec = tuple[float, float, float]
Part = tuple[str, str, Vec, Vec, "float | str"]
RoomSlab = tuple[
    str, str, Vec, Vec, float
]  # (name, 'floor'|'wall', centre, size, tone)
Params = dict[str, float]

APRON_DEPTH_M = 8.0  # floor extends to Y = -8 m (and 8 m past each side wall)
APRON_TONE = 0.8
WALL_T = 0.05


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(max(value, lo), hi)


def _box(name: str, centre: Vec, size: Vec, tone: float | str = 1.0) -> Part:
    return (name, "box", centre, size, tone)


def _cyl(name: str, centre: Vec, size: Vec, tone: float | str = 1.0) -> Part:
    return (name, "cylinder", centre, size, tone)


def box_kind(w: float, d: float, h: float, p: Params) -> list[Part]:
    return [_box("body", (0.0, 0.0, h / 2), (w, d, h))]


def cylinder_kind(w: float, d: float, h: float, p: Params) -> list[Part]:
    return [_cyl("body", (0.0, 0.0, h / 2), (w, d, h))]


def cabinet(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Body + N drawer fronts (params.drawers, default 3) each with a dark handle."""
    n = int(_clamp(p.get("drawers", 3), 1, 8))
    body_d = d * 0.94
    parts = [_box("body", (0.0, d * 0.03, h / 2), (w, body_d, h))]
    slot = h / n
    front_y = -d / 2 + d * 0.02
    for i in range(n):
        z = slot * (i + 0.5)
        parts.append(
            _box(f"drawer{i}", (0.0, front_y, z), (w * 0.9, d * 0.04, slot * 0.82), 0.9)
        )
        handle_h = min(0.03, slot * 0.12)
        parts.append(
            _box(
                f"handle{i}",
                (0.0, -d / 2 + d * 0.01, z + slot * 0.2),
                (w * 0.24, d * 0.02, handle_h),
                "dark",
            )
        )
    return parts


def chest(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Box body + slightly larger, darker lid on top."""
    body_h = h * 0.78
    return [
        _box("body", (0.0, 0.0, body_h / 2), (w * 0.96, d * 0.96, body_h)),
        _box("lid", (0.0, 0.0, body_h + (h - body_h) / 2), (w, d, h - body_h), 0.82),
    ]


def legged(w: float, d: float, h: float, top: float, inset: float) -> list[Part]:
    """Top slab + 4 square legs (table / bench)."""
    top = _clamp(top, 0.02, h * 0.5)
    leg = _clamp(min(w, d) * 0.08, 0.03, 0.08)
    lx = max(w / 2 - inset - leg / 2, 0.0)
    ly = max(d / 2 - inset - leg / 2, 0.0)
    leg_h = h - top
    parts = [_box("top", (0.0, 0.0, h - top / 2), (w, d, top))]
    for i, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        parts.append(
            _box(f"leg{i}", (sx * lx, sy * ly, leg_h / 2), (leg, leg, leg_h), 0.75)
        )
    return parts


def table(w: float, d: float, h: float, p: Params) -> list[Part]:
    return legged(w, d, h, p.get("top", 0.05), p.get("leg_inset", 0.04))


def bench(w: float, d: float, h: float, p: Params) -> list[Part]:
    return legged(w, d, h, p.get("top", max(0.06, h * 0.12)), p.get("leg_inset", 0.06))


def shelf(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Two sides + back panel + N evenly spaced shelves (params.shelves, default 4)."""
    th = _clamp(p.get("thickness", 0.03), 0.01, min(w, d) / 4)
    n = int(_clamp(p.get("shelves", 4), 2, 10))
    parts = [
        _box("side_l", (-w / 2 + th / 2, 0.0, h / 2), (th, d, h)),
        _box("side_r", (w / 2 - th / 2, 0.0, h / 2), (th, d, h)),
        _box("back", (0.0, d / 2 - th / 2, h / 2), (w - 2 * th, th, h), 0.8),
    ]
    step = (h - th) / (n - 1)
    for i in range(n):
        parts.append(
            _box(
                f"shelf{i}", (0.0, -th / 2, th / 2 + i * step), (w - 2 * th, d - th, th)
            )
        )
    return parts


def stool(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Round seat + 3 or 4 thin legs (params.legs)."""
    n = 3 if p.get("legs", 4) < 4 else 4
    seat = min(0.05, h * 0.2)
    leg = _clamp(min(w, d) * 0.1, 0.02, 0.05)
    radius = max(min(w, d) / 2 - leg, 0.0) * 0.8
    parts = [_cyl("seat", (0.0, 0.0, h - seat / 2), (w, d, seat))]
    start = math.pi / 4 if n == 4 else -math.pi / 2
    for i in range(n):
        ang = start + 2 * math.pi * i / n
        x, y = radius * math.cos(ang), radius * math.sin(ang)
        parts.append(
            _cyl(f"leg{i}", (x, y, (h - seat) / 2), (leg, leg, h - seat), 0.75)
        )
    return parts


def door(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Wall-mounted: frame (2 jambs + head) + recessed panel + dark knob on the front."""
    f = _clamp(w * 0.07, 0.03, 0.08)
    knob = min(0.07, d * 0.5, w * 0.1)
    return [
        _box("jamb_l", (-w / 2 + f / 2, 0.0, h / 2), (f, d, h), 0.8),
        _box("jamb_r", (w / 2 - f / 2, 0.0, h / 2), (f, d, h), 0.8),
        _box("head", (0.0, 0.0, h - f / 2), (w - 2 * f, d, f), 0.8),
        _box("panel", (0.0, d / 4, (h - f) / 2), (w - 2 * f, d / 2, h - f)),
        (
            "knob",
            "sphere",
            (w / 2 - f - 0.08 * w, -d / 2 + knob / 2, h * 0.47),
            (knob, knob, knob),
            "dark",
        ),
    ]


def window(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Wall-mounted at params.sill_z (default 0.9 m): frame + cross mullions + pale glass."""
    z0 = max(p.get("sill_z", 0.9), 0.0)
    f = _clamp(min(w, h) * 0.08, 0.02, 0.06)
    zc = z0 + h / 2
    return [
        _box("frame_l", (-w / 2 + f / 2, 0.0, zc), (f, d, h)),
        _box("frame_r", (w / 2 - f / 2, 0.0, zc), (f, d, h)),
        _box("frame_t", (0.0, 0.0, z0 + h - f / 2), (w - 2 * f, d, f)),
        _box("frame_b", (0.0, 0.0, z0 + f / 2), (w - 2 * f, d, f)),
        _box("mullion_v", (0.0, 0.0, zc), (f * 0.6, d * 0.6, h - 2 * f)),
        _box("mullion_h", (0.0, 0.0, zc), (w - 2 * f, d * 0.6, f * 0.6)),
        _box("glass", (0.0, 0.0, zc), (w - 2 * f, d * 0.2, h - 2 * f), 1.35),
    ]


def toolbox(w: float, d: float, h: float, p: Params) -> list[Part]:
    """Box body + carry handle (two posts and a bar)."""
    body_h = h * 0.72
    post = _clamp(min(w, d) * 0.12, 0.01, 0.03)
    post_h = h - body_h
    px = w * 0.3
    return [
        _box("body", (0.0, 0.0, body_h / 2), (w, d, body_h)),
        _box("post_l", (-px, 0.0, body_h + post_h / 2), (post, post, post_h), "dark"),
        _box("post_r", (px, 0.0, body_h + post_h / 2), (post, post, post_h), "dark"),
        _box("bar", (0.0, 0.0, h - post / 2), (2 * px + post, post, post), "dark"),
    ]


KIND_BUILDERS: dict[str, Callable[[float, float, float, Params], list[Part]]] = {
    "box": box_kind, "cylinder": cylinder_kind, "cabinet": cabinet, "chest": chest,
    "bench": bench, "table": table, "shelf": shelf, "stool": stool, "door": door,
    "window": window, "toolbox": toolbox,
}  # fmt: skip


def piece_parts(
    kind: str, size: Vec, params: Params | None = None, shape: str = "box"
) -> list[Part]:
    """Parts for a kind inside `size` (W, D, H); unknown kinds -> box, legacy shape honoured."""
    w, d, h = (max(v, 0.01) for v in size)
    if kind == "box" and shape == "cylinder":
        kind = "cylinder"
    builder = KIND_BUILDERS.get(kind, box_kind)
    return builder(w, d, h, params or {})


def room_slabs(width: float, depth: float, height: float) -> list[RoomSlab]:
    """Floor, back/side walls and the darker apron (top 3 mm below z=0, out to Y=-8 m)."""
    t, apron = WALL_T, APRON_DEPTH_M
    side_x = width / 2 + t / 2
    return [
        ("floor", "floor", (0.0, depth / 2, -t / 2), (width + 2 * t, depth + 2 * t, t), 1.0),
        ("wall_back", "wall", (0.0, depth + t / 2, height / 2), (width + 2 * t, t, height), 1.0),
        ("wall_left", "wall", (-side_x, depth / 2, height / 2), (t, depth, height), 1.0),
        ("wall_right", "wall", (side_x, depth / 2, height / 2), (t, depth, height), 1.0),
        ("apron", "floor", (0.0, (depth + 1.0 - apron) / 2, -0.053),
         (width + 2 * apron, depth + apron + 1.0, 0.1), APRON_TONE),
    ]  # fmt: skip

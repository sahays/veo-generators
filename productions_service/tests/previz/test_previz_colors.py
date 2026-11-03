"""Previz colours: pastel-background sheets resolve to the subject, cast colours stay apart."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from storygraph.previz.layout.colors import delta_e, distinct_colors, dominant_color


def _sheet(bg: str, figure: str, accent: str) -> bytes:
    """A pastel diorama sheet: soft background, a saturated figure, a small skin accent."""
    img = Image.new("RGB", (240, 240), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle((90, 50, 150, 210), fill=figure)  # body, centred
    draw.ellipse((100, 20, 140, 60), fill=accent)  # head
    draw.rectangle(
        (0, 200, 240, 240), fill="#d9b8a0"
    )  # pastel floor strip at the border
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def test_pastel_background_sheet_gives_the_teal_figure() -> None:
    color = dominant_color(_sheet("#ecd3b1", "#1f9e96", "#d9a07a"))
    r, g, b = _rgb(color)
    assert g > r + 60 and b > r + 50  # teal, not the beige page nor the skin head
    assert delta_e(color, "#1f9e96") < 10


def test_yellow_jacket_beats_terracotta_skin_on_mint_background() -> None:
    color = dominant_color(_sheet("#d2ded7", "#f2c418", "#c8785a"))
    assert delta_e(color, "#f2c418") < 10


def test_cast_colours_that_clash_are_rotated_deterministically() -> None:
    colors = {"char_a": "#1f9e96", "char_b": "#22a199", "char_c": "#f2c418"}
    out = distinct_colors(colors, ["char_a", "char_b", "char_c"])
    assert out["char_a"] == "#1f9e96" and out["char_c"] == "#f2c418"  # untouched
    assert out["char_b"] != "#22a199"
    assert all(
        delta_e(out[a], out[b]) >= 20
        for a, b in (("char_a", "char_b"), ("char_a", "char_c"), ("char_b", "char_c"))
    )
    assert distinct_colors(colors, ["char_a", "char_b", "char_c"]) == out

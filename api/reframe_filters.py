"""FFmpeg filter string generation for smart reframing.

Pure string construction — no subprocess calls. Generates crop/scale/blur
filter expressions for the 9:16 crop and 4:5 blurred-background reframing modes.
"""

from typing import List, Tuple

# Output canvas (width, height) per selectable output aspect ratio. The canvas
# width is always 1080; only the height changes. The tightest (full-bleed) rung
# of a canvas equals its aspect ratio — see RUNGS_BY_CANVAS in reframe_plan.
OUTPUT_CANVAS = {
    "9:16": (1080, 1920),
    "3:4": (1080, 1440),
}


def _to_pixel_keypoints(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    crop_w: int,
    max_x: int,
) -> List[Tuple[float, int]]:
    """Convert fractional x keypoints to pixel offsets for crop left-edge."""
    result = []
    for t, x_frac, _ in keypoints:
        center_px = float(x_frac) * src_w
        left_px = max(0, min(max_x, center_px - crop_w / 2))
        result.append((float(t), int(left_px)))
    return result


def _even(n: int) -> int:
    """Round down to the nearest even int (libx264 + yuv420p require even dims)."""
    return int(n) - (int(n) % 2)


def crop_geometry(
    inner_ar: Tuple[int, int], src_w: int, src_h: int
) -> Tuple[int, int, int]:
    """Canonical per-segment crop geometry for an inner aspect ratio.

    Returns `(crop_w, fg_h, max_x)` in source/canvas pixels:
      - `crop_w` — width of the full-height source slice that is kept (the crop
        always takes the full `src_h`, so subjects are only ever cut horizontally).
      - `fg_h` — foreground height on the 1080×1920 canvas; `1920 - fg_h` is the
        letterbox blur-bar height (0 for a full-bleed rung like 9:16).
      - `max_x` — `src_w - crop_w`, the max left-edge offset for the crop window.

    Single source of truth shared by `build_canvas_filter` (renderer) and the
    reference-free eval (`reframe_eval`), so both reason about identical windows.
    """
    aw, ah = inner_ar
    out_w = 1080
    fg_h = _even(round(out_w * ah / aw))
    crop_w = _even(min(int(src_h * aw / ah), src_w))
    max_x = src_w - crop_w
    return crop_w, fg_h, max_x


def _crop_x_offset(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    crop_w: int,
    max_x: int,
) -> str:
    """Build the crop left-edge offset (a constant or a clamped time expression)."""
    pixel_kps = _to_pixel_keypoints(keypoints, src_w, crop_w, max_x)
    if not pixel_kps:
        return str(max(0, (src_w - crop_w) // 2))
    if len(pixel_kps) == 1:
        return str(pixel_kps[0][1])
    x_expr = _build_piecewise_linear_expr(pixel_kps)
    return f"clip({x_expr}\\,0\\,{max_x})"


def crop_left_px_at(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    crop_w: int,
    max_x: int,
    t: float,
) -> float:
    """Crop left-edge (px) at time t — the single source of truth for the pan
    x(t) that the FFmpeg filter encodes.

    Mirrors `_crop_x_offset` / `build_canvas_filter` exactly: keypoints become
    per-keypoint *clamped* pixel left-edges (`_to_pixel_keypoints`), are
    interpolated piecewise-linearly in pixel space, then clamped to [0, max_x].
    The reference-free eval reconstructs the crop window from this, so its idea of
    what got rendered can never drift from the filter — a contract test
    (`test_render_eval_contract`) pins this against the emitted FFmpeg expression.
    """
    if crop_w <= 0 or max_x <= 0:
        return 0.0
    pix = _to_pixel_keypoints(keypoints, src_w, crop_w, max_x)
    if not pix:
        return float(max(0, (src_w - crop_w) // 2))
    if len(pix) == 1 or t <= pix[0][0]:
        val: float = pix[0][1]
    elif t >= pix[-1][0]:
        val = pix[-1][1]
    else:
        val = pix[-1][1]  # ≥ last boundary → hold last (matches the expr fallback)
        for (t0, x0), (t1, x1) in zip(pix, pix[1:]):
            if t < t1:
                val = x0 if t1 == t0 else x0 + (x1 - x0) * (t - t0) / (t1 - t0)
                break
    return float(min(max(val, 0.0), max_x))


def build_canvas_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    inner_ar: Tuple[int, int],
    out_w: int = 1080,
    out_h: int = 1920,
) -> str:
    """Unified per-segment filter_complex for any inner aspect ratio.

    Crops a slice of the source matching `inner_ar`, scales it to fill the canvas
    width, and centers it vertically over a blurred full-canvas background.
    Subsumes the full-bleed and letterboxed cases. Output label is [v].

    The canvas is `out_w`×`out_h` (default 9:16 1080×1920; pass 1080×1440 for 3:4).
    A rung whose `fg_h >= out_h` is full-bleed (no bars); a shorter `fg_h` letterboxes.
    inner_ar examples on a 9:16 canvas: (9,16) full-bleed, (4,5), (1,1), (16,9) letterbox.
    """
    crop_w, fg_h, max_x = crop_geometry(inner_ar, src_w, src_h)
    if crop_w <= 0:
        return f"[0:v]scale={out_w}:{out_h}[v]"
    x_off = _crop_x_offset(keypoints, src_w, crop_w, max_x)
    fg_chain = f"crop={crop_w}:{src_h}:{x_off}:0,scale={out_w}:{fg_h}"

    if fg_h >= out_h:  # full-bleed (e.g. 9:16) — foreground covers the canvas
        return f"[0:v]{fg_chain}[v]"

    y_off = (out_h - fg_h) // 2
    bg = _blurred_bg_base(out_w, out_h)
    return f"{bg};[0:v]{fg_chain}[fg];[bg][fg]overlay=0:{y_off}[v]"


def split_panel_geometry(
    src_w: int, src_h: int, out_w: int = 1080, out_h: int = 1920
) -> Tuple[int, int, int]:
    """Per-panel crop geometry for the stacked vertical-split layout.

    Each of the two panels is `out_w × (out_h/2)`; a panel crops the full source
    height (subjects only ever cut horizontally) at the panel's aspect ratio,
    then scales to fill the panel. Returns `(crop_w, panel_h, max_x)`.
    """
    panel_h = _even(out_h // 2)
    crop_w = _even(min(int(src_h * out_w / panel_h), src_w))
    max_x = src_w - crop_w
    return crop_w, panel_h, max_x


def build_split_filter(
    top_keypoints: List[Tuple[float, float, float]],
    bot_keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    out_w: int = 1080,
    out_h: int = 1920,
) -> str:
    """filter_complex for a stacked two-shot: left subject on top, right on bottom.

    Two full-height source slices (each panned to follow its subject) scaled to
    half-canvas panels and vstacked — no blurred background, since the panels fill
    the canvas. Output label is [v].
    """
    crop_w, panel_h, max_x = split_panel_geometry(src_w, src_h, out_w, out_h)
    if crop_w <= 0:
        return f"[0:v]scale={out_w}:{out_h}[v]"
    top_x = _crop_x_offset(top_keypoints, src_w, crop_w, max_x)
    bot_x = _crop_x_offset(bot_keypoints, src_w, crop_w, max_x)
    return (
        f"[0:v]crop={crop_w}:{src_h}:{top_x}:0,scale={out_w}:{panel_h}[top];"
        f"[0:v]crop={crop_w}:{src_h}:{bot_x}:0,scale={out_w}:{panel_h}[bot];"
        f"[top][bot]vstack[v]"
    )


def _blurred_bg_base(out_w: int, out_h: int) -> str:
    """Background layer: scaled + heavily blurred source."""
    return (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=40[bg]"
    )


def _build_piecewise_linear_expr(keypoints: List[Tuple[float, int]]) -> str:
    """Build balanced binary-tree of if(lt(t,...)) for piecewise-linear x(t).

    Uses O(log n) nesting depth instead of O(n) to avoid hitting FFmpeg's
    expression parser recursion limit (~100 levels).
    """
    if len(keypoints) == 1:
        return str(keypoints[0][1])

    # Build list of (t_boundary, segment_expr) pairs
    segments: List[Tuple[float, str]] = []
    for i in range(len(keypoints) - 1):
        t0, x0 = keypoints[i]
        t1, x1 = keypoints[i + 1]
        if t1 == t0 or x1 == x0:
            seg = str(x0)
        else:
            seg = f"{x0}+{x1 - x0}*(t-{t0:.3f})/{t1 - t0:.3f}"
        segments.append((t1, seg))

    last_val = str(keypoints[-1][1])
    return _build_balanced_expr(segments, 0, len(segments), last_val)


def _build_balanced_expr(
    segments: List[Tuple[float, str]],
    lo: int,
    hi: int,
    fallback: str,
) -> str:
    """Recursively build a balanced if-tree over segments[lo:hi]."""
    if lo >= hi:
        return fallback
    if lo + 1 == hi:
        t, seg = segments[lo]
        return f"if(lt(t\\,{t:.3f})\\,{seg}\\,{fallback})"
    mid = (lo + hi) // 2
    t_mid = segments[mid][0]
    left = _build_balanced_expr(segments, lo, mid, segments[mid][1])
    right = _build_balanced_expr(segments, mid + 1, hi, fallback)
    return f"if(lt(t\\,{t_mid:.3f})\\,{left}\\,{right})"

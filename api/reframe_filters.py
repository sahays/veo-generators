"""FFmpeg filter string generation for smart reframing.

Pure string construction — no subprocess calls. Generates crop/scale/blur
filter expressions for the 9:16 crop and 4:5 blurred-background reframing modes.
"""

from typing import List, Tuple


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


def build_crop_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
) -> str:
    """Generate crop + scale filter for 9:16 dynamic panning (1080x1920 output)."""
    crop_w = int(src_h * 9 / 16)
    max_x = src_w - crop_w
    if max_x <= 0:
        return "scale=1080:1920"

    pixel_kps = _to_pixel_keypoints(keypoints, src_w, crop_w, max_x)
    if not pixel_kps:
        return (
            f"crop={crop_w}:{src_h}:{max(0, (src_w - crop_w) // 2)}:0,scale=1080:1920"
        )
    if len(pixel_kps) == 1:
        return f"crop={crop_w}:{src_h}:{pixel_kps[0][1]}:0,scale=1080:1920"

    x_expr = _build_piecewise_linear_expr(pixel_kps)
    return f"crop={crop_w}:{src_h}:clip({x_expr}\\,0\\,{max_x}):0,scale=1080:1920"


def build_blurred_bg_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
) -> str:
    """Generate filter_complex for 9:16 blurred-background reframe (1080x1920 output).

    Content is cropped at 4:5, scaled to 1080x1350, and centered vertically
    over a blurred full-frame background that fills 1080x1920.
    """
    out_w, out_h = 1080, 1920
    fg_w, fg_h = 1080, 1350
    y_offset = (out_h - fg_h) // 2  # 285
    crop_w = min(int(src_h * 4 / 5), src_w)
    max_x = src_w - crop_w
    bg = _blurred_bg_base(out_w, out_h)

    if max_x <= 0 or not keypoints:
        return f"{bg};[0:v]scale={fg_w}:{fg_h}[fg];[bg][fg]overlay=0:{y_offset}[v]"

    pixel_kps = _to_pixel_keypoints(keypoints, src_w, crop_w, max_x)
    if len(pixel_kps) <= 1:
        x = pixel_kps[0][1] if pixel_kps else max(0, (src_w - crop_w) // 2)
        return (
            f"{bg};[0:v]crop={crop_w}:{src_h}:{x}:0,"
            f"scale={fg_w}:{fg_h}[fg];[bg][fg]overlay=0:{y_offset}[v]"
        )

    x_expr = _build_piecewise_linear_expr(pixel_kps)
    return (
        f"{bg};"
        f"[0:v]crop={crop_w}:{src_h}:clip({x_expr}\\,0\\,{max_x}):0[cropped];"
        f"[cropped]scale={fg_w}:{fg_h}[fg];"
        f"[bg][fg]overlay=0:{y_offset}[v]"
    )


def _even(n: int) -> int:
    """Round down to the nearest even int (libx264 + yuv420p require even dims)."""
    return int(n) - (int(n) % 2)


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


def build_canvas_filter(
    keypoints: List[Tuple[float, float, float]],
    src_w: int,
    src_h: int,
    inner_ar: Tuple[int, int],
) -> str:
    """Unified per-segment filter_complex for any inner aspect ratio.

    Crops a slice of the source matching `inner_ar`, scales it to fill the 1080px
    canvas width, and centers it vertically over a blurred full-canvas background.
    Subsumes the 9:16 (full-bleed) and 4:5 cases. Output label is [v].

    inner_ar examples: (9,16) full-bleed, (4,5), (1,1), (16,9) letterbox.
    """
    aw, ah = inner_ar
    out_w, out_h = 1080, 1920
    fg_h = _even(round(out_w * ah / aw))
    crop_w = _even(min(int(src_h * aw / ah), src_w))
    if crop_w <= 0:
        return f"[0:v]scale={out_w}:{out_h}[v]"
    max_x = src_w - crop_w
    x_off = _crop_x_offset(keypoints, src_w, crop_w, max_x)
    fg_chain = f"crop={crop_w}:{src_h}:{x_off}:0,scale={out_w}:{fg_h}"

    if fg_h >= out_h:  # full-bleed (e.g. 9:16) — foreground covers the canvas
        return f"[0:v]{fg_chain}[v]"

    y_off = (out_h - fg_h) // 2
    bg = _blurred_bg_base(out_w, out_h)
    return f"{bg};[0:v]{fg_chain}[fg];[bg][fg]overlay=0:{y_off}[v]"


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

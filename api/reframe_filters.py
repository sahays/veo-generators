"""FFmpeg filter string generation for smart reframing.

Pure string construction — no subprocess calls. Generates crop/scale/blur
filter expressions for 9:16, 4:5, and vertical-split reframing modes.
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
    """Generate filter_complex for 4:5 blurred-background reframe (1080x1350 output)."""
    out_w, out_h = 1080, 1350
    crop_w = min(int(src_h * 4 / 5), src_w)
    max_x = src_w - crop_w
    bg = _blurred_bg_base(out_w, out_h)

    if max_x <= 0 or not keypoints:
        return f"{bg};[0:v]scale={out_w}:{out_h}[fg];[bg][fg]overlay=0:0[v]"

    pixel_kps = _to_pixel_keypoints(keypoints, src_w, crop_w, max_x)
    if len(pixel_kps) <= 1:
        x = pixel_kps[0][1] if pixel_kps else max(0, (src_w - crop_w) // 2)
        return (
            f"{bg};[0:v]crop={crop_w}:{src_h}:{x}:0,"
            f"scale={out_w}:{out_h}[fg];[bg][fg]overlay=0:0[v]"
        )

    x_expr = _build_piecewise_linear_expr(pixel_kps)
    return (
        f"{bg};"
        f"[0:v]crop={crop_w}:{src_h}:clip({x_expr}\\,0\\,{max_x}):0[cropped];"
        f"[cropped]scale={out_w}:{out_h}[fg];"
        f"[bg][fg]overlay=0:0[v]"
    )


def _blurred_bg_base(out_w: int, out_h: int) -> str:
    """Background layer: scaled + heavily blurred source."""
    return (
        f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
        f"crop={out_w}:{out_h},gblur=sigma=40[bg]"
    )


def build_vertical_split_filter(src_w: int, src_h: int) -> str:
    """Two 4:3 crops stacked vertically with divider (1080x1920 output)."""
    crop_w = min(int(src_h * 4 / 3), src_w)
    right_x = max(0, src_w - crop_w)
    half_h = 959

    return (
        f"[0:v]crop={crop_w}:{src_h}:0:0,scale=-1:{half_h},"
        f"crop=1080:{half_h}:(iw-1080)/2:0[top];"
        f"[0:v]crop={crop_w}:{src_h}:{right_x}:0,scale=-1:{half_h},"
        f"crop=1080:{half_h}:(iw-1080)/2:0[bot];"
        f"color=white:1080x2:d=1[div];"
        f"[top][div][bot]vstack=inputs=3[v]"
    )


def _build_piecewise_linear_expr(keypoints: List[Tuple[float, int]]) -> str:
    """Build nested if(lt(t,...)) FFmpeg expression for piecewise-linear x(t)."""
    if len(keypoints) == 1:
        return str(keypoints[0][1])

    expr = str(keypoints[-1][1])
    for i in range(len(keypoints) - 2, -1, -1):
        t0, x0 = keypoints[i]
        t1, x1 = keypoints[i + 1]
        if t1 == t0 or x1 == x0:
            seg = str(x0)
        else:
            seg = f"{x0}+{x1 - x0}*(t-{t0:.3f})/{t1 - t0:.3f}"
        expr = f"if(lt(t\\,{t1:.3f})\\,{seg}\\,{expr})"
    return expr

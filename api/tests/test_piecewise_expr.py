"""Unit tests for FFmpeg piecewise linear expression — verify correctness."""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import _build_piecewise_linear_expr


def _eval_ffmpeg_expr(expr: str, t: float) -> float:
    """Evaluate a simplified FFmpeg piecewise expression at time t.

    Handles nested if(lt(t\\,T)\\,THEN\\,ELSE) with linear interpolation.
    This is a mini-interpreter for the expressions we generate.
    """
    # Unescape FFmpeg commas
    s = expr.replace("\\,", ",")
    return _eval(s, t)


def _eval(s: str, t: float) -> float:
    """Recursively evaluate if(lt(t,T),THEN,ELSE) or a linear expression."""
    s = s.strip()

    # Base case: plain number
    try:
        return float(s)
    except ValueError:
        pass

    # if(lt(t,T),THEN,ELSE)
    if s.startswith("if(lt(t,"):
        # Parse: if(lt(t,T),THEN,ELSE)
        inner = s[3:-1]  # strip "if(" and ")"
        # Find lt(t,T) — get T
        lt_end = inner.index(")")
        t_val = float(inner[5:lt_end])  # "lt(t,T" -> T

        # Split remaining ",THEN,ELSE" — need to handle nested parens
        rest = inner[lt_end + 2 :]  # skip "),"
        then_part, else_part = _split_top_level(rest)

        if t < t_val:
            return _eval(then_part, t)
        return _eval(else_part, t)

    # Linear: "X0+DX*(t-T0)/DT"
    m = re.match(r"^(-?\d+)\+(-?\d+)\*\(t-([0-9.]+)\)/([0-9.]+)$", s)
    if m:
        x0 = float(m.group(1))
        dx = float(m.group(2))
        t0 = float(m.group(3))
        dt = float(m.group(4))
        return x0 + dx * (t - t0) / dt

    raise ValueError(f"Cannot parse expression: {s}")


def _split_top_level(s: str) -> tuple:
    """Split 'THEN,ELSE' at the top-level comma (not inside parens)."""
    depth = 0
    for i, c in enumerate(s):
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            return s[:i], s[i + 1 :]
    raise ValueError(f"Cannot split: {s}")


class TestPiecewiseExpr:
    def test_single_keypoint(self):
        expr = _build_piecewise_linear_expr([(0.0, 500)])
        assert expr == "500"

    def test_two_keypoints_at_start(self):
        expr = _build_piecewise_linear_expr([(0.0, 100), (10.0, 900)])
        val = _eval_ffmpeg_expr(expr, 0.0)
        assert abs(val - 100) < 1

    def test_two_keypoints_at_end(self):
        expr = _build_piecewise_linear_expr([(0.0, 100), (10.0, 900)])
        val = _eval_ffmpeg_expr(expr, 10.0)
        assert abs(val - 900) < 1

    def test_two_keypoints_midpoint(self):
        expr = _build_piecewise_linear_expr([(0.0, 100), (10.0, 900)])
        val = _eval_ffmpeg_expr(expr, 5.0)
        assert abs(val - 500) < 1

    def test_three_keypoints(self):
        expr = _build_piecewise_linear_expr([(0.0, 0), (5.0, 500), (10.0, 1000)])
        assert abs(_eval_ffmpeg_expr(expr, 0.0) - 0) < 1
        assert abs(_eval_ffmpeg_expr(expr, 5.0) - 500) < 1
        assert abs(_eval_ffmpeg_expr(expr, 10.0) - 1000) < 1
        assert abs(_eval_ffmpeg_expr(expr, 2.5) - 250) < 1

    def test_constant_segments(self):
        """Same x value — expression should be just the constant."""
        expr = _build_piecewise_linear_expr([(0.0, 500), (5.0, 500), (10.0, 500)])
        val_0 = _eval_ffmpeg_expr(expr, 0.0)
        val_5 = _eval_ffmpeg_expr(expr, 5.0)
        val_10 = _eval_ffmpeg_expr(expr, 10.0)
        assert val_0 == val_5 == val_10 == 500

    def test_pan_left_to_right(self):
        """Pan from left edge to right edge."""
        expr = _build_piecewise_linear_expr([(0.0, 0), (10.0, 1313)])
        assert _eval_ffmpeg_expr(expr, 0.0) == 0
        assert abs(_eval_ffmpeg_expr(expr, 10.0) - 1313) < 1
        mid = _eval_ffmpeg_expr(expr, 5.0)
        assert 600 < mid < 700  # ~656.5

    def test_many_keypoints(self):
        """10 keypoints — verify monotonic interpolation."""
        kps = [(float(i), i * 100) for i in range(10)]
        expr = _build_piecewise_linear_expr(kps)
        for i in range(10):
            val = _eval_ffmpeg_expr(expr, float(i))
            assert abs(val - i * 100) < 1

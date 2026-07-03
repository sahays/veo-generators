"""Tests for the L1 pan-path optimizer (focal_path.l1_pan_path)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# L1 pan-path optimization (discretized DP)
# ---------------------------------------------------------------------------
from focal_path import l1_pan_path  # noqa: E402


def _pts(series):
    # series: list of (t, x)
    return [{"time_sec": t, "x": x} for t, x in series]


class TestL1PanPath:
    def test_jitter_inside_window_is_a_hold(self):
        # Detection noise around 0.5 within the containment window → NO motion:
        # exactly two keypoints at the same x.
        pts = _pts([(t, 0.5 + 0.02 * (-1) ** t) for t in range(8)])
        path = l1_pan_path(pts, 0.0, 8.0, contain_w=0.08, max_velocity=0.15)
        assert len(path) == 2
        assert abs(path[0][1] - path[-1][1]) < 1e-9

    def test_walking_subject_yields_one_clean_pan(self):
        # Subject walks 0.25 → 0.75 at constant speed: piecewise path with only
        # a few slope changes (pan-in, track, settle) — not a keypoint per sample.
        pts = _pts([(t, 0.25 + 0.05 * t) for t in range(11)])
        path = l1_pan_path(pts, 0.0, 10.0, contain_w=0.06, max_velocity=0.3)
        assert len(path) <= 6
        xs = [x for _, x in path]
        assert all(b >= a - 1e-9 for a, b in zip(xs, xs[1:]))  # monotone
        assert xs[-1] > 0.6  # caught up with the subject

    def test_speed_is_hard_capped(self):
        # Target teleports; the path may lag but never exceeds max_velocity.
        pts = _pts([(0, 0.2), (1, 0.2), (1.5, 0.8), (6, 0.8)])
        path = l1_pan_path(pts, 0.0, 6.0, contain_w=0.05, max_velocity=0.12)
        for (t0, x0), (t1, x1) in zip(path, path[1:]):
            if t1 > t0:
                assert abs(x1 - x0) / (t1 - t0) <= 0.12 + 1e-6

    def test_brief_excursion_does_not_wiggle_the_camera(self):
        # A one-sample target spike inside the window (a head turn, a detector
        # blip) must not produce a pan-out-and-back.
        pts = _pts(
            [(t, 0.5) for t in range(4)] + [(4, 0.56)] + [(t, 0.5) for t in range(5, 9)]
        )
        path = l1_pan_path(pts, 0.0, 8.0, contain_w=0.08, max_velocity=0.15)
        assert len(path) == 2

    def test_containment_is_enforced_for_sustained_drift(self):
        # Subject drifts well past the window → the path must follow closely
        # enough that the subject stays near the crop center.
        pts = _pts([(t, 0.2 + 0.04 * t) for t in range(13)])
        path = l1_pan_path(pts, 0.0, 12.0, contain_w=0.05, max_velocity=0.3)
        # check the final position: subject at 0.68, path within window + slack
        assert abs(path[-1][1] - 0.68) <= 0.05 + 0.03

    def test_degenerate_short_segment(self):
        path = l1_pan_path(_pts([(0, 0.4)]), 0.0, 0.3, contain_w=0.08)
        assert len(path) >= 2
        assert all(0.0 <= x <= 1.0 for _, x in path)

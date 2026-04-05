"""Unit tests for focal path smoothing — velocity limiting, scene cuts, dedup."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from focal_path import (
    smooth_focal_path,
    _prepare_focal_points,
    _build_scene_boundaries,
    _apply_velocity_limit,
    _collapse_static_runs,
    _deduplicate,
)


# ---------------------------------------------------------------------------
# smooth_focal_path — integration
# ---------------------------------------------------------------------------


class TestSmoothFocalPath:
    def test_empty_returns_center_pair(self):
        result = smooth_focal_path([], [], duration=10.0, fps=30)
        assert result == [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]

    def test_single_point_produces_valid_path(self):
        fps = [{"time_sec": 5.0, "x": 0.3, "y": 0.5}]
        result = smooth_focal_path(fps, [], duration=10.0, fps=30)
        assert len(result) >= 2
        assert result[0][0] == 0.0
        assert result[-1][0] == 10.0

    def test_all_x_values_in_range(self):
        fps = [
            {"time_sec": 0.0, "x": 0.1, "y": 0.5},
            {"time_sec": 5.0, "x": 0.9, "y": 0.5},
            {"time_sec": 10.0, "x": 0.1, "y": 0.5},
        ]
        result = smooth_focal_path(fps, [], duration=10.0, fps=30)
        for _, x, y in result:
            assert 0.0 <= x <= 1.0
            assert 0.0 <= y <= 1.0

    def test_scene_change_produces_segments(self):
        fps = [
            {"time_sec": 0.0, "x": 0.2, "y": 0.5},
            {"time_sec": 4.9, "x": 0.2, "y": 0.5},
            {"time_sec": 5.1, "x": 0.8, "y": 0.5},
            {"time_sec": 10.0, "x": 0.8, "y": 0.5},
        ]
        sc = [{"time_sec": 5.0}]
        result = smooth_focal_path(fps, sc, duration=10.0, fps=30)
        assert len(result) >= 3

    def test_points_beyond_duration_ignored(self):
        fps = [
            {"time_sec": 0.0, "x": 0.5, "y": 0.5},
            {"time_sec": 100.0, "x": 0.5, "y": 0.5},
        ]
        result = smooth_focal_path(fps, [], duration=10.0, fps=30)
        for t, _, _ in result:
            assert t <= 10.0


# ---------------------------------------------------------------------------
# Velocity limiting
# ---------------------------------------------------------------------------


class TestVelocityLimit:
    def test_slow_movement_unchanged(self):
        kps = [(0.0, 0.5, 0.5), (1.0, 0.55, 0.5)]  # dx=0.05 < max_vel
        result = _apply_velocity_limit(kps, max_velocity=0.15, deadzone=0.02)
        assert abs(result[1][1] - 0.55) < 0.01

    def test_fast_movement_clamped(self):
        kps = [(0.0, 0.0, 0.5), (1.0, 1.0, 0.5)]  # dx=1.0 >> max_vel
        result = _apply_velocity_limit(kps, max_velocity=0.15, deadzone=0.02)
        assert result[1][1] < 0.2  # clamped to ~0.15

    def test_deadzone_suppresses_small_moves(self):
        kps = [(0.0, 0.5, 0.5), (1.0, 0.51, 0.5)]  # dx=0.01 < deadzone
        result = _apply_velocity_limit(kps, max_velocity=0.15, deadzone=0.05)
        assert result[1][1] == 0.5  # suppressed

    def test_empty_keypoints(self):
        assert _apply_velocity_limit([], 0.15, 0.05) == []

    def test_single_keypoint(self):
        result = _apply_velocity_limit([(5.0, 0.3, 0.5)], 0.15, 0.05)
        assert result == [(5.0, 0.3, 0.5)]


# ---------------------------------------------------------------------------
# Static run collapsing
# ---------------------------------------------------------------------------


class TestCollapseStaticRuns:
    def test_all_same_x_keeps_first_last(self):
        kps = [(i, 0.5, 0.5) for i in range(10)]
        result = _collapse_static_runs(kps)
        assert len(result) == 2
        assert result[0] == kps[0]
        assert result[-1] == kps[-1]

    def test_transition_points_kept(self):
        kps = [
            (0, 0.3, 0.5),
            (1, 0.3, 0.5),
            (2, 0.5, 0.5),
            (3, 0.7, 0.5),
            (4, 0.7, 0.5),
        ]
        result = _collapse_static_runs(kps)
        # Should keep: 0 (first), 1 (transition to 0.5), 2 (transition), 3 (transition from 0.7), 4 (last)
        assert len(result) >= 3

    def test_two_points_unchanged(self):
        kps = [(0, 0.3, 0.5), (10, 0.7, 0.5)]
        assert _collapse_static_runs(kps) == kps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestPrepare:
    def test_sorts_by_time(self):
        fps = [
            {"time_sec": 5.0, "x": 0.5, "y": 0.5},
            {"time_sec": 1.0, "x": 0.3, "y": 0.5},
        ]
        result = _prepare_focal_points(fps, 10.0)
        assert result[0]["time_sec"] == 1.0

    def test_clamps_to_duration(self):
        fps = [
            {"time_sec": 5.0, "x": 0.5, "y": 0.5},
            {"time_sec": 15.0, "x": 0.5, "y": 0.5},
        ]
        result = _prepare_focal_points(fps, 10.0)
        assert len(result) == 1


class TestSceneBoundaries:
    def test_always_includes_zero_and_end(self):
        result = _build_scene_boundaries([{"time_sec": 5.0}], 10.0)
        assert result[0] == 0.0
        assert result[-1] == 10.0
        assert 5.0 in result

    def test_empty_scene_changes(self):
        result = _build_scene_boundaries([], 10.0)
        assert result == [0.0, 10.0]

    def test_deduplicates(self):
        result = _build_scene_boundaries([{"time_sec": 0.0}, {"time_sec": 10.0}], 10.0)
        assert result == [0.0, 10.0]


class TestDeduplicate:
    def test_removes_duplicate_times(self):
        kps = [(1.0, 0.3, 0.5), (1.0, 0.5, 0.5), (2.0, 0.5, 0.5)]
        result = _deduplicate(kps)
        assert len(result) == 2

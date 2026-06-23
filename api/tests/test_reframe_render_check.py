"""Unit tests for the sampled render-output check (pure logic + blank detection).

The decode+detect orchestration runs in the worker (needs ffmpeg/MediaPipe); here
we test the placement prediction, the aggregation/flagging, and blank detection on
synthetic frames — all host-runnable.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_filters import crop_geometry  # noqa: E402
from reframe_render_check import (  # noqa: E402
    POS_TOL,
    _kp_x,
    _predicted_out_x,
    _sample_indices,
    _summarize,
)

SRC_W, SRC_H = 1920, 1080


# ---------------------------------------------------------------------------
# Placement prediction (plan → expected output-x)
# ---------------------------------------------------------------------------


class TestPredictedOutX:
    def test_centered_subject_maps_to_mid_output(self):
        # Crop centered on a mid-frame subject (unclamped) → subject at out_x ~0.5.
        crop_w, _fg, max_x = crop_geometry((9, 16), SRC_W, SRC_H)
        crop = {"keypoints": [(0.0, 0.5, 0.5), (10.0, 0.5, 0.5)]}
        assert abs(_predicted_out_x(crop, SRC_W, crop_w, max_x, 5.0) - 0.5) < 1e-6

    def test_edge_subject_shifts_off_center(self):
        # Subject hard against the left edge → crop clamps, subject sits left of mid.
        crop_w, _fg, max_x = crop_geometry((9, 16), SRC_W, SRC_H)
        crop = {"keypoints": [(0.0, 0.0, 0.5), (10.0, 0.0, 0.5)]}
        out_x = _predicted_out_x(crop, SRC_W, crop_w, max_x, 5.0)
        assert out_x < 0.5  # left subject lands left of center
        assert 0.0 <= out_x <= 1.0

    def test_kp_x_interpolates(self):
        kps = [(0.0, 0.2, 0.5), (10.0, 0.8, 0.5)]
        assert abs(_kp_x(kps, 5.0) - 0.5) < 1e-9
        assert _kp_x(kps, -1.0) == 0.2  # held before first
        assert _kp_x(kps, 99.0) == 0.8  # held after last


# ---------------------------------------------------------------------------
# Sampling + aggregation
# ---------------------------------------------------------------------------


class TestSampleIndices:
    def test_all_when_fewer_than_budget(self):
        assert _sample_indices(3, 12) == [0, 1, 2]

    def test_evenly_spaced_and_capped(self):
        idx = _sample_indices(100, 5)
        assert idx[0] == 0 and idx[-1] == 99
        assert len(idx) == 5

    def test_empty(self):
        assert _sample_indices(0, 12) == []


class TestSummarize:
    def test_empty_is_empty(self):
        assert _summarize(0, 0, 0, 0, [], 0, 0, []) == {}

    def test_clean_run_is_ok(self):
        b = _summarize(10, 10, 8, 8, [0.02, 0.03], 0, 0, [])
        assert b["nonblank_rate"] == 1.0
        assert b["face_present_rate"] == 1.0
        assert b["flag"] == "ok"

    def test_black_output_fails(self):
        # Most frames blank → nonblank_rate collapses → fail.
        b = _summarize(10, 2, 0, 0, [], 0, 0, [(1.0, "blank")])
        assert b["nonblank_rate"] == 0.2
        assert b["flag"] == "fail"

    def test_misplaced_faces_flag(self):
        # Faces present but far from predicted x → position error trips a flag.
        b = _summarize(10, 10, 6, 6, [0.4, 0.45, 0.5], 0, 0, [])
        assert b["position_error_p90"] >= 0.30
        assert b["flag"] == "fail"

    def test_split_panel_gap_flags(self):
        # Only half the split panels showed a person → panel-fill flag.
        b = _summarize(6, 6, 0, 0, [], 6, 12, [(2.0, "split panel empty")])
        assert b["split_panel_fill_rate"] == 0.5
        assert b["flag"] == "fail"


# ---------------------------------------------------------------------------
# Blank-frame detection (synthetic frames, cv2 on host)
# ---------------------------------------------------------------------------


class TestBlankDetection:
    def test_black_and_textured(self):
        pytest.importorskip("cv2")
        import numpy as np

        from reframe_render_check import _is_blank

        black = np.zeros((1920, 1080, 3), dtype=np.uint8)
        assert _is_blank(black) is True

        # A noisy frame has high variance → not blank.
        rng = np.random.default_rng(0)
        noise = rng.integers(0, 255, (1920, 1080, 3), dtype=np.uint8)
        assert _is_blank(noise) is False


def test_pos_tol_is_sane():
    assert 0.0 < POS_TOL < 0.5

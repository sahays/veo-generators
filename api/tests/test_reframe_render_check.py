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


# ---------------------------------------------------------------------------
# Real-FFmpeg integration: source → plan → render → check (worker image only).
# ffmpeg is absent on the host venv, so these skip there; they run in the worker
# container (`docker run … pytest`), which has ffmpeg + cv2 + MediaPipe.
# ---------------------------------------------------------------------------

import shutil  # noqa: E402
import subprocess  # noqa: E402

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
_needs_ffmpeg = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")


def _ffmpeg(args):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
        capture_output=True,
    )


@_needs_ffmpeg
class TestRealRenderIntegration:
    SRC_W, SRC_H = 1280, 720
    DUR = 3.0

    def _testsrc(self, path):
        # Colourful, never-blank source.
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=size={self.SRC_W}x{self.SRC_H}:rate=25:duration={self.DUR}",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ]
        )

    def _bar_src(self, path, frac_x):
        # Mid-grey base with a bright vertical bar at source-x = frac_x — a movable
        # "subject" whose output position we can locate by brightest column.
        bx = f"iw*{frac_x}-4"
        _ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=gray:size={self.SRC_W}x{self.SRC_H}:rate=25:duration={self.DUR}",
                "-vf",
                f"drawbox=x={bx}:y=0:w=8:h=ih:color=white:t=fill",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ]
        )

    def test_render_seam_nonblank(self, tmp_path):
        # Real planner (empty detections → centre crops) → real render → check_render.
        from reframe_plan import attach_keypoints, reconcile
        from reframe_render_check import check_render
        from reframe_service import render_plan

        src = tmp_path / "src.mp4"
        out = tmp_path / "out.mp4"
        self._testsrc(src)
        segs = reconcile(
            [], [], cuts=[], src_w=self.SRC_W, src_h=self.SRC_H, duration=self.DUR
        )
        attach_keypoints(segs, 25.0)
        render_plan(str(src), str(out), segs, self.SRC_W, self.SRC_H, has_audio=False)
        block = check_render(str(out), segs, self.SRC_W, self.SRC_H, 1080, 1920)
        assert block, "check_render returned no block for a real render"
        # testsrc2 is never blank → the decode/blank path must agree.
        assert block["nonblank_rate"] == 1.0
        assert block["flag"] != "fail"

    def test_predicted_vs_actual_placement(self, tmp_path):
        # The crux: render a known subject and confirm it LANDS where the plan
        # predicts. Build a bar at source-x, force a crop that follows it, render
        # for real, then locate the bar in the OUTPUT and compare to _predicted_out_x.
        import cv2

        from reframe_filters import crop_geometry
        from reframe_render_check import _predicted_out_x
        from reframe_service import render_plan

        for frac_x in (0.5, 0.7, 0.95):  # centred, off-centre, edge-clamped
            src = tmp_path / f"bar_{int(frac_x * 100)}.mp4"
            out = tmp_path / f"barout_{int(frac_x * 100)}.mp4"
            self._bar_src(src, frac_x)
            crop = {
                "track_id": None,
                "source": "center",
                "x_target": frac_x,
                "keypoints": [(0.0, frac_x, 0.5), (self.DUR, frac_x, 0.5)],
            }
            seg = {
                "start": 0.0,
                "end": self.DUR,
                "layout": "single",
                "inner_ar": (9, 16),
                "crops": [crop],
            }
            render_plan(
                str(src), str(out), [seg], self.SRC_W, self.SRC_H, has_audio=False
            )

            crop_w, _fg, max_x = crop_geometry((9, 16), self.SRC_W, self.SRC_H)
            pred = _predicted_out_x(crop, self.SRC_W, crop_w, max_x, self.DUR / 2)

            cap = cv2.VideoCapture(str(out))
            cap.set(cv2.CAP_PROP_POS_MSEC, (self.DUR / 2) * 1000)
            ok, frame = cap.read()
            cap.release()
            assert ok and frame is not None
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            col_brightness = gray.mean(axis=0)  # per-column mean over height
            actual = int(col_brightness.argmax()) / frame.shape[1]
            assert abs(actual - pred) < 0.04, (
                f"frac_x={frac_x}: bar at out_x={actual:.3f}, plan predicted {pred:.3f}"
            )

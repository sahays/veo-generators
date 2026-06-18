"""Unit tests for diagnostic-mode helpers — label ranking, lookups, interpolation."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reframe_diagnostic import (
    CANVAS_W,
    CANVAS_H,
    track_label_map,
    _nearest_tracks,
    _scene_at,
    _interp_x,
)


def _tf(time_sec, track_ids):
    return {"time_sec": time_sec, "tracks": [{"track_id": t} for t in track_ids]}


class TestTrackLabelMap:
    def test_ranks_by_frequency(self):
        # track 7 appears 3x, track 2 appears 2x, track 5 appears 1x.
        frames = [_tf(0, [7, 2, 5]), _tf(2, [7, 2]), _tf(4, [7])]
        labels = track_label_map(frames)
        assert labels[7] == "A"  # most visible
        assert labels[2] == "B"
        assert labels[5] == "C"

    def test_empty(self):
        assert track_label_map([]) == {}

    def test_more_than_26_tracks_uses_id(self):
        frames = [_tf(0, list(range(30)))]
        labels = track_label_map(frames)
        # 27th-ranked track falls back to its numeric id (all tie → id order)
        assert any(v.isdigit() for v in labels.values())


class TestNearestTracks:
    def test_holds_last_sample(self):
        frames = [_tf(0.0, [1]), _tf(2.0, [2])]
        times = [0.0, 2.0]
        assert _nearest_tracks(frames, times, 0.0)[0]["track_id"] == 1
        assert _nearest_tracks(frames, times, 1.9)[0]["track_id"] == 1  # held
        assert _nearest_tracks(frames, times, 2.0)[0]["track_id"] == 2
        assert _nearest_tracks(frames, times, 99)[0]["track_id"] == 2  # clamps

    def test_empty(self):
        assert _nearest_tracks([], [], 1.0) == []


class TestSceneAt:
    def test_picks_active_scene(self):
        scenes = [
            {"start_sec": 0.0, "scene_type": "a"},
            {"start_sec": 5.0, "scene_type": "b"},
        ]
        starts = [0.0, 5.0]
        assert _scene_at(scenes, starts, 1.0)["scene_type"] == "a"
        assert _scene_at(scenes, starts, 5.0)["scene_type"] == "b"
        assert _scene_at(scenes, starts, 10.0)["scene_type"] == "b"

    def test_empty(self):
        assert _scene_at([], [], 1.0) is None


class TestInterpX:
    def test_linear_midpoint(self):
        kps = [(0.0, 0.2, 0.5), (10.0, 0.8, 0.5)]
        assert abs(_interp_x(kps, 5.0) - 0.5) < 1e-6

    def test_clamps_ends(self):
        kps = [(2.0, 0.3, 0.5), (8.0, 0.7, 0.5)]
        assert _interp_x(kps, 0.0) == 0.3
        assert _interp_x(kps, 99.0) == 0.7

    def test_empty_defaults_center(self):
        assert _interp_x([], 1.0) == 0.5


def test_canvas_is_portrait_1080x1920():
    assert (CANVAS_W, CANVAS_H) == (1080, 1920)

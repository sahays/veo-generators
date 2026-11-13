"""Window planner, window splitting and filmstrip layout invariants."""

from __future__ import annotations

import random

import pytest

from timeline_windows import (
    DEFAULT_MAX_WINDOW_SEC,
    FILMSTRIP_MAX_TILES,
    MIN_SPLIT_SEC,
    Window,
    can_split,
    covers_whole_video,
    nearest_cut,
    plan_filmstrip,
    plan_windows,
    split_window,
)


def _assert_exact_cover(windows: list[Window], duration: float, cap: float) -> None:
    """Windows partition `[0, duration]`: no gap, no overlap, none over the cap."""
    assert [w.index for w in windows] == list(range(len(windows)))
    assert windows[0].start_sec == 0.0
    assert windows[-1].end_sec == duration
    for before, after in zip(windows, windows[1:]):
        assert after.start_sec == before.end_sec
    for window in windows:
        assert 0 < window.length_sec <= cap + 1e-6


def test_short_video_is_one_window_covering_everything() -> None:
    windows = plan_windows(187.4, [10.0, 50.0, 120.0], max_window_sec=600.0)
    assert windows == [Window(0, 0.0, 187.4)]
    assert covers_whole_video(windows[0], 187.4)


def test_duration_equal_to_the_cap_is_still_one_window() -> None:
    cap = DEFAULT_MAX_WINDOW_SEC
    assert plan_windows(cap, [cap / 2]) == [Window(0, 0.0, cap)]
    assert len(plan_windows(cap + 0.01, [])) == 2


def test_default_window_is_five_minutes() -> None:
    # Longer windows mis-ordered scenes and under-reported dialogue in a live run.
    assert DEFAULT_MAX_WINDOW_SEC == 300.0
    assert len(plan_windows(1040.28, [])) == 4


def test_long_video_without_cuts_splits_evenly() -> None:
    windows = plan_windows(1500.0, [], max_window_sec=600.0)
    assert [(w.start_sec, w.end_sec) for w in windows] == [
        (0.0, 500.0),
        (500.0, 1000.0),
        (1000.0, 1500.0),
    ]
    assert not covers_whole_video(windows[0], 1500.0)


@pytest.mark.parametrize("seed", range(25))
def test_random_plans_are_gap_free_non_overlapping_and_capped(seed: int) -> None:
    rng = random.Random(seed)
    duration = rng.uniform(1.0, 9000.0)
    cap = rng.choice([60.0, 300.0, 600.0])
    cuts = [rng.uniform(-5.0, duration + 5.0) for _ in range(rng.randint(0, 400))]
    windows = plan_windows(duration, cuts, max_window_sec=cap)
    _assert_exact_cover(windows, duration, cap)
    assert sum(w.length_sec for w in windows) == pytest.approx(duration)
    assert len(windows) == 1 or duration > cap


def test_boundary_snaps_to_the_nearest_cut_within_tolerance() -> None:
    # Even boundaries would be 500 and 1000. 492 is nearer to 500 than 511.
    windows = plan_windows(1500.0, [492.0, 511.0, 1013.5], max_window_sec=600.0)
    assert [w.end_sec for w in windows] == [492.0, 1013.5, 1500.0]
    _assert_exact_cover(windows, 1500.0, 600.0)


def test_boundary_ignores_cuts_beyond_the_tolerance() -> None:
    # 40 s away from the even boundary: too far to be worth moving for.
    windows = plan_windows(1500.0, [460.0, 1040.0], max_window_sec=600.0)
    assert [w.end_sec for w in windows] == [500.0, 1000.0, 1500.0]


def test_unsorted_duplicate_and_out_of_range_cuts_are_tolerated() -> None:
    cuts = [1013.5, 492.0, 492.0, -3.0, 0.0, 1500.0, 99999.0]
    windows = plan_windows(1500.0, cuts, max_window_sec=600.0)
    assert [w.end_sec for w in windows] == [492.0, 1013.5, 1500.0]


def test_non_positive_window_cap_is_rejected() -> None:
    with pytest.raises(ValueError):
        plan_windows(100.0, [], max_window_sec=0.0)


def test_nearest_cut_prefers_the_earlier_cut_on_an_exact_tie() -> None:
    assert nearest_cut([90.0, 110.0], 100.0, 15.0) == 90.0
    assert nearest_cut([90.0, 110.0], 100.0, 5.0) is None
    assert nearest_cut([], 100.0, 15.0) is None


def test_split_window_halves_cover_the_parent_and_keep_its_index() -> None:
    parent = Window(3, 1200.0, 1800.0)
    first, second = split_window(parent, [])
    assert (first.start_sec, first.end_sec) == (1200.0, 1500.0)
    assert (second.start_sec, second.end_sec) == (1500.0, 1800.0)
    assert first.index == second.index == 3


def test_split_window_snaps_the_midpoint_to_a_cut_inside_the_window() -> None:
    parent = Window(0, 0.0, 600.0)
    # 1200.0 and 0.0 are outside the open interval and must not be chosen.
    first, second = split_window(parent, [0.0, 290.5, 320.0, 1200.0])
    assert first.end_sec == second.start_sec == 290.5


def test_can_split_stops_at_the_minimum_useful_length() -> None:
    assert can_split(Window(0, 0.0, 2 * MIN_SPLIT_SEC))
    assert not can_split(Window(0, 0.0, 2 * MIN_SPLIT_SEC - 0.5))


@pytest.mark.parametrize("duration", [0.4, 1.0, 59.2, 120.0, 121.0, 1800.0, 7200.5])
def test_filmstrip_tiles_cover_the_video_within_the_tile_cap(duration: float) -> None:
    spec = plan_filmstrip(duration, 1920, 1080)
    assert 1 <= spec["count"] <= FILMSTRIP_MAX_TILES
    assert spec["interval_sec"] >= 1 and spec["interval_sec"] == int(
        spec["interval_sec"]
    )
    # The last tile starts before the video ends, and the tiles reach the end.
    assert (spec["count"] - 1) * spec["interval_sec"] < max(duration, 1.0)
    assert spec["count"] * spec["interval_sec"] >= duration
    assert spec["columns"] * spec["rows"] >= spec["count"]
    assert spec["columns"] * (spec["rows"] - 1) < spec["count"]


def test_filmstrip_tile_keeps_aspect_ratio_with_an_even_height() -> None:
    landscape = plan_filmstrip(60.0, 1920, 1080)
    portrait = plan_filmstrip(60.0, 1080, 1920)
    assert (landscape["tile_width"], landscape["tile_height"]) == (160, 90)
    assert (portrait["tile_width"], portrait["tile_height"]) == (160, 284)
    assert plan_filmstrip(60.0, 0, 0)["tile_height"] % 2 == 0

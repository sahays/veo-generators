"""Smoothing, prominence-ranked extrema and steepest declines."""

from __future__ import annotations

import random

import pytest
from signal_peaks import find_drops, find_extrema, smooth

Point = tuple[float, float]


def _series(values: list[float], step: float = 1.0) -> list[Point]:
    return [(index * step, value) for index, value in enumerate(values)]


def _naive_prominence(values: list[float], index: int) -> float:
    """Textbook definition: walk out to the nearest strictly higher sample."""
    left = index
    while left > 0 and values[left - 1] <= values[index]:
        left -= 1
    right = index
    while right < len(values) - 1 and values[right + 1] <= values[index]:
        right += 1
    left_base = min(values[left : index + 1])
    right_base = min(values[index : right + 1])
    return values[index] - max(left_base, right_base)


def _summary(found: list[dict]) -> list[tuple[str, float, float]]:
    return [(item["kind"], item["time_sec"], item["prominence"]) for item in found]


def test_smooth_is_a_centred_average_that_keeps_the_endpoints() -> None:
    points = _series([0.0, 3.0, 6.0, 30.0, 6.0, 3.0, 0.0])
    assert smooth(points, 3) == _series([0.0, 3.0, 13.0, 14.0, 13.0, 3.0, 0.0])
    # Window 5 shrinks to 3 next to the ends instead of looking past them.
    assert smooth(points, 5) == _series([0.0, 3.0, 9.0, 9.6, 9.0, 3.0, 0.0])
    assert smooth(points, 1) == points
    assert smooth(points, 0) == points
    assert smooth(points, 1) is not points  # always a new list


def test_prominence_ranking_matches_a_worked_example() -> None:
    found = find_extrema(_series([0, 5, 2, 8, 1, 3, 0]), min_spacing_sec=0)
    assert _summary(found) == [
        ("peak", 3.0, 8.0),
        ("peak", 1.0, 3.0),
        ("valley", 2.0, 3.0),
        ("valley", 4.0, 2.0),
        ("peak", 5.0, 2.0),
    ]
    assert [item["value"] for item in found] == [8, 5, 2, 1, 3]


@pytest.mark.parametrize(
    "values",
    [
        [4.0] * 12,
        [float(i) for i in range(12)],
        [float(-i) for i in range(12)],
        [1.0, 1.0, 2.0, 2.0, 2.0, 5.0, 5.0],  # non-decreasing with plateaus
        [3.0, 7.0],
        [],
    ],
)
def test_flat_or_monotone_series_has_no_extrema(values: list[float]) -> None:
    assert find_extrema(_series(values), min_spacing_sec=0) == []


def test_smoothed_flat_series_stays_free_of_rounding_noise_extrema() -> None:
    flat = smooth(_series([0.1 + 0.2] * 50), 5)
    assert find_extrema(flat, min_spacing_sec=0) == []
    assert find_drops(flat, window_sec=5) == []


def test_single_bump_is_a_peak_and_never_also_a_valley() -> None:
    """The reference picked global top-N and bottom-N, so short series overlapped."""
    found = find_extrema(_series([1.0, 3.0, 2.0]), min_spacing_sec=0)
    assert _summary(found) == [("peak", 1.0, 1.0)]


@pytest.mark.parametrize("seed", range(25))
def test_random_series_extrema_are_true_turning_points(seed: int) -> None:
    rng = random.Random(seed)
    values = [float(rng.randint(0, 20)) for _ in range(rng.randint(3, 60))]
    found = find_extrema(_series(values), min_spacing_sec=0, max_count=100)
    peaks = {item["time_sec"] for item in found if item["kind"] == "peak"}
    valleys = {item["time_sec"] for item in found if item["kind"] == "valley"}
    assert not peaks & valleys
    assert 0.0 not in peaks | valleys
    assert float(len(values) - 1) not in peaks | valleys
    floor = 0.1 * (max(values) - min(values))
    for item in found:
        index = int(item["time_sec"])
        sign = 1.0 if item["kind"] == "peak" else -1.0
        signed = [sign * value for value in values]
        assert signed[index] >= max(signed[index - 1], signed[index + 1])
        assert item["prominence"] == _naive_prominence(signed, index)
        assert item["prominence"] >= floor
    ordered = sorted(found, key=lambda i: (-i["prominence"], i["time_sec"]))
    assert found == ordered


@pytest.mark.parametrize("seed", range(10))
def test_every_prominent_strict_turning_point_is_reported(seed: int) -> None:
    rng = random.Random(1000 + seed)
    values = rng.sample(range(500), 40)  # distinct values: no plateaus
    found = find_extrema(_series(values), min_spacing_sec=0, max_count=100)
    floor = 0.1 * (max(values) - min(values))
    negated = [-value for value in values]
    expected = set()
    for index in range(1, len(values) - 1):
        before, here, after = values[index - 1 : index + 2]
        if before < here > after and _naive_prominence(values, index) >= floor:
            expected.add(("peak", float(index)))
        if before > here < after and _naive_prominence(negated, index) >= floor:
            expected.add(("valley", float(index)))
    assert {(item["kind"], item["time_sec"]) for item in found} == expected


def test_plateau_yields_one_extremum_at_its_middle() -> None:
    found = find_extrema(_series([0, 1, 3, 3, 3, 1, 0, 0, 0, 2]), min_spacing_sec=0)
    assert _summary(found) == [("peak", 3.0, 3.0), ("valley", 7.0, 2.0)]


def test_spacing_keeps_the_more_prominent_of_two_close_peaks() -> None:
    values = [0.0, 9.0, 4.0, 7.0, 0.0, 0.0, 0.0, 0.0, 8.0, 0.0]
    close = find_extrema(_series(values, step=10.0), min_spacing_sec=30.0)
    peaks = [item["time_sec"] for item in close if item["kind"] == "peak"]
    assert peaks == [10.0, 80.0]  # 30 s (7.0) is within 30 s of the 9.0 peak
    # Spacing applies per kind: the 20 s valley sits 10 s from a kept peak.
    assert [i["time_sec"] for i in close if i["kind"] == "valley"] == [50.0, 20.0]
    loose = find_extrema(_series(values, step=10.0), min_spacing_sec=20.0)
    assert sorted(i["time_sec"] for i in loose if i["kind"] == "peak") == [
        10.0,
        30.0,
        80.0,
    ]


def test_small_wiggles_on_a_trend_are_below_the_prominence_floor() -> None:
    values = [float(i) + (1.5 if i % 2 else 0.0) for i in range(40)]
    values[20] = 60.0
    found = find_extrema(_series(values), min_spacing_sec=0)
    # Only the spike and the low right after it stand out; the 0.5 wiggles do not.
    assert _summary(found) == [("peak", 20.0, 38.0), ("valley", 22.0, 18.5)]
    lenient = find_extrema(
        _series(values), min_spacing_sec=0, max_count=50, min_prominence_ratio=0.0
    )
    assert len(lenient) == 2 + 2 * 17


def test_max_count_limits_each_kind_to_the_most_prominent() -> None:
    values = [0.0, 5.0, 1.0, 9.0, 2.0, 7.0, 3.0, 8.0, 0.0]
    found = find_extrema(_series(values), min_spacing_sec=0, max_count=2)
    assert [i["time_sec"] for i in found if i["kind"] == "peak"] == [3.0, 7.0]
    assert len([i for i in found if i["kind"] == "valley"]) == 2


def test_drop_reports_where_the_fall_starts_and_how_big_it_is() -> None:
    values = [50.0, 50.0, 50.0, 80.0, 80.0, 62.0, 40.0, 41.0, 42.0, 43.0]
    drops = find_drops(_series(values, step=5.0), window_sec=15.0)
    assert drops == [
        {
            "kind": "drop",
            "time_sec": 20.0,  # the later of the two 80s: closest to the fall
            "value": 80.0,
            "prominence": 40.0,
            "end_sec": 30.0,
            "end_value": 40.0,
        }
    ]
    # A window of one sample only sees the steepest single step (62 -> 40).
    step = find_drops(_series(values, step=5.0), window_sec=5.0)
    assert [(d["time_sec"], d["prominence"]) for d in step] == [(25.0, 22.0)]


def test_rising_series_has_no_drops_and_small_falls_are_ignored() -> None:
    assert find_drops(_series([float(i) for i in range(20)]), window_sec=5.0) == []
    values = [100.0 - i for i in range(50)]  # steady decline: 1 per sample
    assert find_drops(_series(values), window_sec=5.0) == []
    assert len(find_drops(_series(values), window_sec=5.0, min_drop_ratio=0.05)) == 3


@pytest.mark.parametrize("seed", range(15))
def test_drops_never_overlap_and_are_ranked_by_size(seed: int) -> None:
    rng = random.Random(seed)
    values = [float(rng.randint(0, 100)) for _ in range(80)]
    drops = find_drops(_series(values, step=2.0), window_sec=8.0, max_count=6)
    assert 1 <= len(drops) <= 6
    sizes = [drop["prominence"] for drop in drops]
    assert sizes == sorted(sizes, reverse=True)
    spans = sorted((drop["time_sec"], drop["end_sec"]) for drop in drops)
    assert all(a[1] < b[0] for a, b in zip(spans, spans[1:]))
    best = max(values[i] - min(values[i + 1 : i + 5]) for i in range(len(values) - 1))
    assert sizes[0] == best
    for drop in drops:
        assert 0 < drop["end_sec"] - drop["time_sec"] <= 8.0
        assert drop["prominence"] == drop["value"] - drop["end_value"]

"""Engagement templates: determinism, sampling rules and distinct profiles."""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

import pytest
from signal_templates import (
    TEMPLATE_METRIC,
    generate_template_series,
    list_templates,
)

_API_DIR = Path(__file__).resolve().parents[2]
_IDS = ["high", "low", "jumpy", "slow_burn", "front_loaded"]


def _values(template_id: str, duration: float = 600.0) -> list[float]:
    series = generate_template_series(template_id, duration, "en-fixed")
    return [value for _, value in series.points]


def _step_size(values: list[float]) -> float:
    return statistics.mean(abs(b - a) for a, b in zip(values, values[1:]))


def test_series_is_identical_in_another_process_with_another_hash_seed() -> None:
    """Python's randomised `hash()` must not leak into the series."""
    script = (
        "import json, sitecustomize\n"
        "from signal_templates import generate_template_series\n"
        "s = generate_template_series('jumpy', 600.0, 'en-abc123')\n"
        "print(json.dumps(s.points))\n"
    )
    runs = [
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=_API_DIR,
            env={**os.environ, "PYTHONHASHSEED": hash_seed},
            capture_output=True,
            text=True,
            check=True,
        )
        for hash_seed in ("1", "987654")
    ]
    here = generate_template_series("jumpy", 600.0, "en-abc123").points
    for run in runs:
        assert [tuple(p) for p in json.loads(run.stdout)] == here


def test_seed_and_template_each_change_the_series() -> None:
    base = generate_template_series("high", 300.0, "en-1").points
    assert generate_template_series("high", 300.0, "en-1").points == base
    other_seed = generate_template_series("high", 300.0, "en-2").points
    assert other_seed != base
    assert [t for t, _ in other_seed] == [t for t, _ in base]
    assert generate_template_series("low", 300.0, "en-1").points != base


@pytest.mark.parametrize(
    ("duration", "interval", "count"),
    [
        (30.0, 1.0, 30),  # duration / 120 < 1 -> clamped up to 1 s
        (600.0, 5.0, 120),
        (880.0, 7.33, 121),  # non-integer interval stays on a 2-decimal grid
        (36000.0, 60.0, 600),  # duration / 120 > 60 -> clamped down to 60 s
        (0.4, 1.0, 1),
    ],
)
def test_sampling_interval_is_clamped(
    duration: float, interval: float, count: int
) -> None:
    series = generate_template_series("slow_burn", duration, "seed")
    times = [t for t, _ in series.points]
    assert series.interval_sec == interval
    assert len(times) == count
    assert times == [round(i * interval, 2) for i in range(count)]
    assert times[-1] < duration
    assert series.duration_sec == duration
    assert series.primary_metric == TEMPLATE_METRIC
    assert list(series.metrics) == [TEMPLATE_METRIC]


@pytest.mark.parametrize("template_id", _IDS)
def test_values_stay_inside_the_index_range(template_id: str) -> None:
    values = _values(template_id)
    assert min(values) >= 0.0
    assert max(values) <= 100.0
    # Noise is small: a sample is never far from the noise-free shape.
    preview = list_templates()[_IDS.index(template_id)]["preview"]
    assert abs(values[0] - preview[0]) <= 3.0
    assert abs(values[-1] - preview[-1]) <= 3.0


def test_profiles_have_distinct_characters() -> None:
    values = {template_id: _values(template_id) for template_id in _IDS}
    means = {key: statistics.mean(series) for key, series in values.items()}
    steps = {key: _step_size(series) for key, series in values.items()}
    assert means["high"] > means["low"] + 40
    assert means["high"] > 70
    assert means["low"] < 35
    assert all(steps["jumpy"] > 2 * steps[key] for key in _IDS if key != "jumpy")

    def peak_position(key: str) -> float:
        series = values[key]
        return max(range(len(series)), key=series.__getitem__) / (len(series) - 1)

    assert peak_position("slow_burn") > 2 / 3
    assert peak_position("front_loaded") < 0.2
    assert peak_position("high") < 0.2
    # low: steady decline; front_loaded: the opening dwarfs the tail.
    low, front = values["low"], values["front_loaded"]
    third = len(low) // 3
    assert statistics.mean(low[:third]) > statistics.mean(low[third : 2 * third])
    assert statistics.mean(low[third : 2 * third]) > statistics.mean(low[2 * third :])
    assert statistics.mean(front[:12]) > 2.5 * statistics.mean(front[30:])
    assert values["slow_burn"][0] < 30 < 70 < max(values["slow_burn"])


def test_list_templates_returns_stable_noise_free_previews() -> None:
    templates = list_templates()
    assert [t["id"] for t in templates] == _IDS
    assert list_templates() == templates
    for template in templates:
        assert set(template) == {"id", "label", "description", "preview"}
        assert len(template["preview"]) == 40
        assert all(0.0 <= v <= 100.0 for v in template["preview"])
        assert template["description"].endswith(".")
        assert template["description"].count(".") == 1
    previews = {t["id"]: t["preview"] for t in templates}
    assert previews["slow_burn"].index(max(previews["slow_burn"])) > 26
    assert previews["front_loaded"].index(max(previews["front_loaded"])) < 8


def test_unknown_template_is_rejected_with_the_valid_ids() -> None:
    with pytest.raises(ValueError, match="Unknown engagement template 'viral'") as err:
        generate_template_series("viral", 60.0, "seed")
    assert all(template_id in str(err.value) for template_id in _IDS)


@pytest.mark.parametrize("duration", [0.0, -5.0, float("nan"), float("inf")])
def test_unusable_duration_is_rejected(duration: float) -> None:
    with pytest.raises(ValueError, match="positive number of seconds"):
        generate_template_series("high", duration, "seed")

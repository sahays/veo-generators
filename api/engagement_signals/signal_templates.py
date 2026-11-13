"""Built-in engagement profiles ("templates") and their deterministic series.

Template curves are simulated shapes, not audience measurements. Each profile is a
closed-form function of normalised time (0 = start of the video, 1 = end) returning
an "Engagement index" in 0..100. Pure module: no I/O.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Callable
from dataclasses import dataclass

from engagement_series import Point, SignalSeries

TEMPLATE_METRIC = "Engagement index"
_PREVIEW_POINTS = 40
_TARGET_SAMPLES = 120
_MIN_INTERVAL_SEC = 1.0
_MAX_INTERVAL_SEC = 60.0
_TAU = 2.0 * math.pi


def _bump(x: float, centre: float, width: float, height: float) -> float:
    """Gaussian bump of `height` centred on `centre`."""
    return height * math.exp(-0.5 * ((x - centre) / width) ** 2)


def _step_down(x: float, at: float, softness: float) -> float:
    """Smooth step from 1 (before `at`) to 0 (after it)."""
    return 1.0 / (1.0 + math.exp((x - at) / softness))


def _high(x: float) -> float:
    """Strong hook, sustained high level, mild decay towards the end."""
    return 80.0 + _bump(x, 0.05, 0.035, 12.0) + 3.0 * math.sin(_TAU * 2.5 * x) - 9.0 * x


def _low(x: float) -> float:
    """Weak opening and a steady decline, with one brief lift and one sag."""
    trend = 34.0 - 20.0 * x + 1.5 * math.sin(_TAU * 2.0 * x)
    return trend + _bump(x, 0.38, 0.04, 5.0) - _bump(x, 0.72, 0.035, 4.0)


def _jumpy(x: float) -> float:
    """Volatile: fast oscillation with sharp isolated spikes and dips."""
    wave = 14.0 * math.sin(_TAU * 5.0 * x + 0.6) + 9.0 * math.sin(_TAU * 11.0 * x + 2.1)
    spikes = _bump(x, 0.18, 0.012, 24.0) + _bump(x, 0.66, 0.012, 28.0)
    dips = _bump(x, 0.41, 0.012, 26.0) + _bump(x, 0.87, 0.012, 24.0)
    return 50.0 + wave + spikes - dips


def _slow_burn(x: float) -> float:
    """Gradual build to a late climax."""
    ripple = 2.0 * math.sin(_TAU * 3.0 * x)
    return 22.0 + 46.0 * x**1.6 + _bump(x, 0.86, 0.07, 20.0) + ripple


def _front_loaded(x: float) -> float:
    """Strong hook, an early sharp drop, then a low tail."""
    ramp = 1.0 - 0.25 * math.exp(-x / 0.015)
    hook = 62.0 * _step_down(x, 0.14, 0.008) * ramp
    return 24.0 + hook - 8.0 * x + 1.5 * math.sin(_TAU * 4.0 * x)


@dataclass(frozen=True)
class _Template:
    """A selectable engagement profile."""

    id: str
    label: str
    description: str
    shape: Callable[[float], float]
    noise: float


_TEMPLATES: dict[str, _Template] = {
    t.id: t
    for t in (
        _Template(
            "high",
            "High engagement",
            "A strong hook and a sustained high level that eases off only mildly.",
            _high,
            1.5,
        ),
        _Template(
            "low",
            "Low engagement",
            "A weak opening that declines steadily to the end.",
            _low,
            1.5,
        ),
        _Template(
            "jumpy",
            "Jumpy",
            "A volatile curve with sharp spikes and dips throughout.",
            _jumpy,
            3.0,
        ),
        _Template(
            "slow_burn",
            "Slow burn",
            "Engagement builds gradually to a climax late in the video.",
            _slow_burn,
            1.5,
        ),
        _Template(
            "front_loaded",
            "Front-loaded",
            "A strong hook, then an early sharp drop and a low tail.",
            _front_loaded,
            1.5,
        ),
    )
}

TEMPLATE_IDS: tuple[str, ...] = tuple(_TEMPLATES)


def _clamp_index(value: float) -> float:
    """Clamp to the 0..100 index range."""
    return min(100.0, max(0.0, value))


def _require_template(template_id: str) -> _Template:
    """Return the template or raise `ValueError` naming the valid ids."""
    template = _TEMPLATES.get(template_id)
    if template is None:
        valid = ", ".join(TEMPLATE_IDS)
        raise ValueError(
            f"Unknown engagement template '{template_id}'. Choose one of: {valid}."
        )
    return template


def _seeded_rng(template_id: str, seed: str) -> random.Random:
    """RNG seeded from a stable digest, identical across processes and platforms."""
    digest = hashlib.sha256(f"{template_id}|{seed}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def template_interval(duration_sec: float) -> float:
    """Sampling interval for a video: `clamp(duration / 120, 1, 60)` seconds."""
    raw = duration_sec / _TARGET_SAMPLES
    return round(min(_MAX_INTERVAL_SEC, max(_MIN_INTERVAL_SEC, raw)), 2)


def list_templates() -> list[dict]:
    """Return every template as an `EngagementTemplate` dict with a noise-free preview."""
    last = _PREVIEW_POINTS - 1
    return [
        {
            "id": t.id,
            "label": t.label,
            "description": t.description,
            "preview": [
                round(_clamp_index(t.shape(i / last)), 1)
                for i in range(_PREVIEW_POINTS)
            ],
        }
        for t in _TEMPLATES.values()
    ]


def generate_template_series(
    template_id: str, duration_sec: float, seed: str
) -> SignalSeries:
    """Sample a template over `duration_sec` with small seeded noise.

    Deterministic for `(template_id, duration_sec, seed)`. Raises `ValueError`
    for an unknown template or a non-positive / non-finite duration.
    """
    template = _require_template(template_id)
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise ValueError("Template duration must be a positive number of seconds.")
    interval = template_interval(duration_sec)
    count = max(1, math.ceil(duration_sec / interval - 1e-9))
    rng = _seeded_rng(template_id, seed)
    points: list[Point] = []
    for i in range(count):
        x = i / (count - 1) if count > 1 else 0.0
        noisy = template.shape(x) + rng.uniform(-template.noise, template.noise)
        points.append((round(i * interval, 2), round(_clamp_index(noisy), 2)))
    return SignalSeries(
        metrics={TEMPLATE_METRIC: points},
        primary_metric=TEMPLATE_METRIC,
        interval_sec=interval,
        duration_sec=float(duration_sec),
    )

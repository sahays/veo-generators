"""Clock abstraction and the adaptive (AIMD) token bucket that paces one model's calls.

Reservation-style bucket: `reserve()` debits a token immediately (the balance may go
negative) and returns how long the caller must sleep before its slot, so concurrent callers
get evenly spaced, FIFO slots with no polling. On a quota signal `throttle()` halves the
rate (multiplicative decrease, at most once per cooldown so one burst of 429s counts once)
and drops any saved burst; the rate then regains `recovery_per_min` of the nominal rate per
quiet minute (additive increase) — converging on the real quota.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class MonotonicClock:
    """Wall clock for production: monotonic time, blocking (non-busy) sleep."""

    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


@dataclass(frozen=True)
class BucketCfg:
    rpm: float
    burst: int = 1
    min_rate_fraction: float = 0.1
    recovery_per_min: float = 0.1
    throttle_cooldown_s: float = 5.0


class AdaptiveTokenBucket:
    """Thread-safe token bucket with reservations and AIMD rate control (rates in calls/s)."""

    def __init__(self, cfg: BucketCfg, clock: Clock) -> None:
        self._nominal = cfg.rpm / 60.0
        self._floor = self._nominal * cfg.min_rate_fraction
        self._recover = self._nominal * cfg.recovery_per_min / 60.0
        self._burst, self._cooldown = float(cfg.burst), cfg.throttle_cooldown_s
        self._rate, self._tokens = self._nominal, float(cfg.burst)
        self._clock = clock
        self._last = clock.now()
        self._throttled_at = -math.inf
        self._lock = threading.Lock()

    @property
    def rpm(self) -> float:
        with self._lock:
            self._advance(self._clock.now())
            return self._rate * 60.0

    def _advance(self, now: float) -> None:
        dt = now - self._last
        if dt <= 0:
            return
        self._tokens = min(self._burst, self._tokens + dt * self._rate)
        self._rate = min(self._nominal, self._rate + dt * self._recover)
        self._last = now

    def reserve(self) -> float:
        """Take the next slot; returns seconds to wait before using it (0 = now)."""
        with self._lock:
            self._advance(self._clock.now())
            self._tokens -= 1.0
            return max(0.0, -self._tokens / self._rate)

    def throttle(self) -> bool:
        """Halve the rate (not below the floor); False if within the cooldown of the last cut."""
        with self._lock:
            now = self._clock.now()
            self._advance(now)
            if now - self._throttled_at < self._cooldown:
                return False
            self._rate = max(self._floor, self._rate / 2.0)
            self._tokens = min(self._tokens, 0.0)
            self._throttled_at = now
            return True

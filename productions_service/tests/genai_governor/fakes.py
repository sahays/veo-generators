"""Test doubles for the GenAI governor: a manual clock and provider-shaped errors."""

from __future__ import annotations

import random
import threading

from storygraph.adapters.governor import Governor
from storygraph.adapters.governor.bucket import Clock
from storygraph.config import GenAIGovernorCfg, ModelLimitCfg


class FakeClock:
    """Deterministic clock: `sleep` advances time instantly and records the request."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self.t

    def sleep(self, seconds: float) -> None:
        with self._lock:
            self.sleeps.append(seconds)
            self.t += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds


class FakeHeaders(dict[str, str]):
    """Case-insensitive `get` like httpx.Headers."""

    def get(self, key: str, default: str | None = None) -> str | None:  # type: ignore[override]
        return next((v for k, v in self.items() if k.lower() == key.lower()), default)


class FakeResponse:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = FakeHeaders(headers)


class FakeApiError(Exception):
    """Shaped like `google.genai.errors.APIError`: code, status, details, response."""

    def __init__(
        self,
        code: int,
        status: str,
        retry_after: str | None = None,
        details: object = None,
    ) -> None:
        self.code, self.status, self.details = code, status, details
        self.response = FakeResponse(
            {"Retry-After": retry_after} if retry_after else {}
        )
        super().__init__(
            f"{code} {status}. Resource exhausted. Please try again later."
        )


def quota_error(retry_after: str | None = None) -> FakeApiError:
    return FakeApiError(429, "RESOURCE_EXHAUSTED", retry_after)


def fake_governor(
    clock: Clock,
    rpm: float = 60.0,
    concurrency: int = 2,
    max_elapsed_s: float = 30.0,
) -> Governor:
    cfg = GenAIGovernorCfg(
        max_elapsed_s=max_elapsed_s,
        base_backoff_s=2.0,
        max_backoff_s=8.0,
        throttle_cooldown_s=0.0,
        default=ModelLimitCfg(rpm=rpm, concurrency=concurrency, burst=1),
        models={},
    )
    return Governor(cfg, clock=clock, rng=random.Random(7))

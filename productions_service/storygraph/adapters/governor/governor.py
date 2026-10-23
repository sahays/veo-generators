"""The process-wide GenAI call governor: one queue, one pacing policy, one retry policy.

`governed(model, fn)` is the single seam every model adapter (image, VLM, Omni video, TTS,
transcribe) wraps its raw provider call in. Per model it keeps a lane = `FifoGate` (bounded
FIFO queue, max concurrency) + `AdaptiveTokenBucket` (rpm, AIMD on 429). Each attempt:

    queue for a slot -> sleep until the bucket's next slot -> call -> release the slot

Quota / transient / empty-response errors are retried with full-jitter exponential back-off
(Retry-After / retryDelay honoured) until `max_elapsed_s`, then raise `QuotaExhausted` or
`TransientModelError` with the attempt count. Fatal errors propagate unchanged at once.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar, cast

from ...config import GenAIGovernorCfg
from .bucket import AdaptiveTokenBucket, BucketCfg, Clock, MonotonicClock
from .classify import Kind, Verdict, classify
from .context import current_scope
from .errors import (
    GovernorSaturated,
    ModelCallError,
    QuotaExhausted,
    TransientModelError,
)
from .gate import FifoGate, QueueFull

T = TypeVar("T")
_log = logging.getLogger(__name__)
_SLOW_WAIT_S = 1.0  # successful calls that queued longer than this are logged at INFO


@dataclass(frozen=True)
class Lane:
    gate: FifoGate
    bucket: AdaptiveTokenBucket


@dataclass
class _Run:
    model: str
    start: float
    attempts: int = 0
    empties: int = 0
    waited_s: float = 0.0
    last: tuple[Verdict, Exception] | None = None  # most recent retryable failure


class Governor:
    def __init__(
        self,
        cfg: GenAIGovernorCfg,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.cfg, self.clock = cfg, clock or MonotonicClock()
        self._rng = rng or random.Random()
        self._lanes: dict[str, Lane] = {}
        self._lock = threading.Lock()

    def lane(self, model: str) -> Lane:
        """The model's lane, created once (double-checked under the registry lock)."""
        found = self._lanes.get(model)
        if found is not None:
            return found
        with self._lock:
            if model not in self._lanes:
                self._lanes[model] = self._build_lane(model)
            return self._lanes[model]

    def _build_lane(self, model: str) -> Lane:
        lim, c = self.cfg.limit_for(model), self.cfg
        bucket_cfg = BucketCfg(
            lim.rpm,
            lim.burst,
            c.min_rate_fraction,
            c.recovery_per_min,
            c.throttle_cooldown_s,
        )
        gate = FifoGate(lim.concurrency, c.queue_capacity)
        return Lane(gate, AdaptiveTokenBucket(bucket_cfg, self.clock))

    def call(self, model: str, fn: Callable[[], T]) -> T:
        """Run `fn` (one raw provider request) under `model`'s queue, pacing and retries."""
        lane, run = self.lane(model), _Run(model, self.clock.now())
        while True:
            done, value, delay = self._attempt(lane, run, fn)
            if done:
                return cast(T, value)
            self.clock.sleep(delay)

    def _elapsed(self, run: _Run) -> float:
        return self.clock.now() - run.start

    def _admit(self, lane: Lane, run: _Run) -> None:
        """Queue for a slot, then sleep until the bucket's slot (both within budget)."""
        queued_at = self.clock.now()
        try:
            got = lane.gate.acquire(self.cfg.max_elapsed_s - self._elapsed(run))
        except QueueFull as exc:
            raise GovernorSaturated(run.model, run.attempts, 0.0, str(exc)) from exc
        if not got:
            raise GovernorSaturated(
                run.model, run.attempts, self._elapsed(run), "queue wait"
            )
        wait = lane.bucket.reserve()
        if run.last is not None and self._elapsed(run) + wait > self.cfg.max_elapsed_s:
            lane.gate.release()
            raise self._exhausted(run)
        self.clock.sleep(wait)
        run.waited_s += self.clock.now() - queued_at

    def _attempt(
        self, lane: Lane, run: _Run, fn: Callable[[], T]
    ) -> tuple[bool, T | None, float]:
        """(done, value, back-off delay); raises when the error is fatal or out of budget."""
        self._admit(lane, run)
        run.attempts += 1
        try:
            value = fn()
        except Exception as exc:
            delay = self._retry_delay(lane, run, exc)
            if delay is None:
                raise
            return False, None, delay
        finally:
            lane.gate.release()
        self._log_success(run)
        return True, value, 0.0

    def _backoff(self, attempt: int, hint: float | None) -> float:
        """Full jitter U(0, min(cap, base*2^(n-1))); a server hint wins (+ small jitter)."""
        base, cap = self.cfg.base_backoff_s, self.cfg.max_backoff_s
        if hint is not None:
            return hint + self._rng.uniform(0.0, base)
        return self._rng.uniform(0.0, min(cap, base * 2 ** (attempt - 1)))

    def _retry_delay(self, lane: Lane, run: _Run, exc: Exception) -> float | None:
        """Back-off before the next attempt; None = re-raise `exc` unchanged."""
        verdict = classify(exc)
        if verdict.kind is Kind.FATAL:
            return None
        if verdict.kind is Kind.EMPTY:
            run.empties += 1
            if run.empties > self.cfg.max_empty_retries:
                return None
        run.last = (verdict, exc)
        cut = verdict.kind is Kind.QUOTA and lane.bucket.throttle()
        delay = self._backoff(run.attempts, verdict.retry_after_s)
        if self._elapsed(run) + delay > self.cfg.max_elapsed_s:
            raise self._exhausted(run)
        how = f"back-off {delay:.1f}s; rate {lane.bucket.rpm:.1f} rpm"
        self._log(run, logging.WARNING, "genai call retrying", verdict, str(exc), how)
        if cut:
            _log_throttle(run, lane.bucket.rpm)
        return delay

    def _exhausted(self, run: _Run) -> ModelCallError:
        """Typed give-up for the last retryable failure (the next try would overrun)."""
        err = _give_up(run, self._elapsed(run))
        verdict = run.last[0] if run.last else None
        self._log(run, logging.ERROR, "genai call gave up", verdict, err.cause)
        return err

    def _log_success(self, run: _Run) -> None:
        slow = run.attempts > 1 or run.waited_s > _SLOW_WAIT_S
        level = logging.INFO if slow else logging.DEBUG
        self._log(run, level, "genai call succeeded", None, "ok")

    def _log(
        self,
        run: _Run,
        level: int,
        what: str,
        verdict: Verdict | None,
        why: str,
        how: str = "",
    ) -> None:
        extra: dict[str, Any] = {
            "who": "storygraph.adapters.governor",
            "where": current_scope(),
            "what": f"{what} ({run.model}, attempt {run.attempts})",
            "when": datetime.now(UTC).isoformat(),
            "why": f"{verdict.kind.value}: {why[:300]}" if verdict else why,
            "how": how or f"queue+token wait {run.waited_s:.1f}s",
            "model": run.model,
            "attempt": run.attempts,
            "wait_s": round(run.waited_s, 2),
            "elapsed_s": round(self.clock.now() - run.start, 2),
        }
        _log.log(level, what, extra=extra)


def _give_up(run: _Run, elapsed: float) -> ModelCallError:
    assert run.last is not None  # only called after a retryable failure
    verdict, exc = run.last
    kind = QuotaExhausted if verdict.kind is Kind.QUOTA else TransientModelError
    err = kind(run.model, run.attempts, elapsed, str(exc))
    err.__cause__ = exc
    return err


def _log_throttle(run: _Run, rpm: float) -> None:
    _log.warning(
        "genai rate cut",
        extra={
            "who": "storygraph.adapters.governor",
            "where": current_scope(),
            "what": f"{run.model} rate halved to {rpm:.1f} rpm",
            "when": datetime.now(UTC).isoformat(),
            "why": "429 / RESOURCE_EXHAUSTED: the configured rpm exceeds the live quota",
            "how": "AIMD: multiplicative decrease now, additive recovery per quiet minute",
        },
    )

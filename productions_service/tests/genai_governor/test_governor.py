"""GenAI governor: pacing, AIMD, Retry-After, give-up, classification, concurrency bounds."""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from genai_governor.fakes import FakeApiError, FakeClock, fake_governor, quota_error

from storygraph.adapters.governor import (
    EmptyModelResponse,
    QuotaExhausted,
    TransientModelError,
)
from storygraph.adapters.governor.bucket import (
    AdaptiveTokenBucket,
    BucketCfg,
    MonotonicClock,
)
from storygraph.adapters.governor.classify import Kind, classify
from storygraph.adapters.governor.gate import FifoGate, QueueFull
from storygraph.config import Config, GenAIGovernorCfg, KeyframesCfg
from storygraph.errors import StoryGraphError


class Flaky:
    """Callable failing with `errors` in order, then returning "ok"; counts calls."""

    def __init__(self, *errors: Exception, always: Exception | None = None) -> None:
        self.errors, self.always, self.calls = list(errors), always, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.always is not None:
            raise self.always
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def test_bucket_spaces_slots_halves_on_quota_and_recovers_slowly() -> None:
    clock = FakeClock()
    bucket = AdaptiveTokenBucket(BucketCfg(rpm=60, burst=1), clock)
    assert [bucket.reserve() for _ in range(3)] == [0.0, 1.0, 2.0]  # FIFO slots, 1/s
    clock.advance(3.0)
    assert bucket.throttle() and bucket.rpm == pytest.approx(30.0)
    assert bucket.reserve() == pytest.approx(2.0)  # saved burst dropped, half rate
    assert not bucket.throttle()  # same burst of 429s inside the cooldown counts once
    clock.advance(60.0)  # one quiet minute regains 10% of nominal (additive increase)
    assert bucket.rpm == pytest.approx(36.0)
    for _ in range(10):
        clock.advance(6.0)
        bucket.throttle()
    assert bucket.rpm >= 6.0 - 1e-9  # floor: min_rate_fraction of nominal


def test_sequential_calls_are_paced_by_the_bucket() -> None:
    clock = FakeClock()
    gov = fake_governor(clock, rpm=60)
    assert [gov.call("m", lambda: "ok") for _ in range(4)] == ["ok"] * 4
    assert clock.sleeps == [0.0, 1.0, 1.0, 1.0]


def test_retry_after_is_honoured_and_the_model_rate_is_cut() -> None:
    clock = FakeClock()
    gov = fake_governor(clock, rpm=60)
    fn = Flaky(quota_error(retry_after="7"))
    assert gov.call("m", fn) == "ok" and fn.calls == 2
    backoffs = [s for s in clock.sleeps if s >= 7.0]
    assert len(backoffs) == 1 and backoffs[0] <= 7.0 + 2.0  # hint + U(0, base)
    assert gov.lane("m").bucket.rpm < 31.0  # AIMD halved 60 -> 30 (plus tiny recovery)


@pytest.mark.parametrize(
    ("exc", "kind", "hint"),
    [
        (quota_error(), Kind.QUOTA, None),
        (FakeApiError(429, "RESOURCE_EXHAUSTED", details={"retryDelay": "12s"}), Kind.QUOTA, 12.0),
        (FakeApiError(503, "UNAVAILABLE"), Kind.TRANSIENT, None),
        (FakeApiError(504, "DEADLINE_EXCEEDED"), Kind.TRANSIENT, None),
        (httpx.ConnectError("reset by peer"), Kind.TRANSIENT, None),
        (FakeApiError(400, "INVALID_ARGUMENT"), Kind.FATAL, None),
        (EmptyModelResponse("no image data"), Kind.EMPTY, None),
        (StoryGraphError("wrapped: 429 RESOURCE_EXHAUSTED"), Kind.QUOTA, None),
        (StoryGraphError("shot_429 has a bad prop"), Kind.FATAL, None),
    ],
)  # fmt: skip
def test_classification(exc: Exception, kind: Kind, hint: float | None) -> None:
    verdict = classify(exc)
    assert verdict.kind is kind and verdict.retry_after_s == hint


def test_quota_cause_is_found_through_a_wrapping_error() -> None:
    try:
        try:
            raise quota_error(retry_after="3")
        except FakeApiError as inner:
            raise StoryGraphError("GeminiImageGenerator failed") from inner
    except StoryGraphError as outer:
        verdict = classify(outer)
    assert verdict.kind is Kind.QUOTA and verdict.retry_after_s == 3.0


def test_persistent_quota_gives_up_typed_with_attempt_count() -> None:
    clock = FakeClock()
    gov = fake_governor(clock, max_elapsed_s=30.0)
    fn = Flaky(always=quota_error())
    with pytest.raises(QuotaExhausted) as info:
        gov.call("m", fn)
    err = info.value
    assert err.attempts == fn.calls > 2 and err.elapsed_s <= 30.0
    assert str(err).startswith(f"quota exhausted after {fn.calls} attempt(s)")
    assert clock.now() <= 30.0  # never sleeps past the budget


def test_transient_gives_up_typed_and_fatal_is_not_retried() -> None:
    gov = fake_governor(FakeClock(), max_elapsed_s=20.0)
    with pytest.raises(TransientModelError):
        gov.call("m", Flaky(always=FakeApiError(503, "UNAVAILABLE")))
    fatal = Flaky(always=FakeApiError(400, "INVALID_ARGUMENT"))
    with pytest.raises(FakeApiError):
        gov.call("m", fatal)
    assert fatal.calls == 1


def test_empty_responses_are_retried_a_bounded_number_of_times() -> None:
    gov = fake_governor(FakeClock())
    fn = Flaky(always=EmptyModelResponse("returned no image data"))
    with pytest.raises(EmptyModelResponse):
        gov.call("m", fn)
    assert fn.calls == gov.cfg.max_empty_retries + 1


def test_gate_is_fifo_bounded_and_hands_slots_over_in_order() -> None:
    gate, order = FifoGate(concurrency=1, capacity=2), []
    assert gate.acquire(1.0)

    def waiter(name: str) -> None:
        assert gate.acquire(5.0)
        order.append(name)
        gate.release()

    threads = []
    for i, name in enumerate(("first", "second")):
        threads.append(threading.Thread(target=waiter, args=(name,)))
        threads[-1].start()
        while gate.queued < i + 1:
            time.sleep(0.001)
    with pytest.raises(QueueFull):
        gate.acquire(0.1)
    gate.release()
    for t in threads:
        t.join(2.0)
    assert order == ["first", "second"]


def test_concurrency_never_exceeds_the_model_limit_under_threads() -> None:
    gov = fake_governor(MonotonicClock(), rpm=60_000, concurrency=2)
    active, peak, lock = 0, 0, threading.Lock()

    def work() -> str:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return "ok"

    results: list[str] = []
    threads = [
        threading.Thread(target=lambda: results.append(gov.call("m", work)))
        for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
    assert results == ["ok"] * 10 and peak == 2


def test_default_yaml_mirrors_code_defaults() -> None:
    """config.py and config/default.yaml must not drift (the deployed service reads YAML)."""
    cfg = Config.load()
    assert cfg.genai == GenAIGovernorCfg() and cfg.keyframes == KeyframesCfg()

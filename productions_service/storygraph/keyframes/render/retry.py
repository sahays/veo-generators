"""Bounded retry with back-off for transient provider errors (quota / capacity / 5xx).

Adapters wrap provider failures in `StoryGraphError` with the provider message, so transient
failures are recognised by their status markers. Non-transient errors propagate immediately.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final, TypeVar

from ...errors import StoryGraphError

T = TypeVar("T")
_log = logging.getLogger(__name__)
TRANSIENT_MARKERS: Final[tuple[str, ...]] = (
    "429",
    "RESOURCE_EXHAUSTED",
    "503",
    "UNAVAILABLE",
    "500 INTERNAL",
    "DEADLINE_EXCEEDED",
    "no image data",  # the image model answered with text only: stochastic, retry
)


def is_transient(exc: Exception) -> bool:
    text = str(exc)
    return any(m in text for m in TRANSIENT_MARKERS)


def with_retry(
    fn: Callable[[], T],
    what: str,
    tries: int = 4,
    base_delay_s: float = 8.0,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """Call `fn`; on a transient `StoryGraphError` wait base*2^k and retry (≤ `tries`)."""
    for attempt in range(tries):
        try:
            return fn()
        except StoryGraphError as exc:
            if attempt + 1 >= tries or not is_transient(exc):
                raise
            delay = base_delay_s * 2**attempt
            _log.warning(
                "transient provider error, retrying",
                extra={
                    "who": "storygraph.keyframes.retry",
                    "where": what,
                    "what": f"attempt {attempt + 1}/{tries} failed",
                    "when": datetime.now(UTC).isoformat(),
                    "why": str(exc)[:300],
                    "how": f"exponential back-off {delay:.0f}s",
                },
            )
            (sleep or time.sleep)(delay)
    raise StoryGraphError(f"{what}: retries exhausted")

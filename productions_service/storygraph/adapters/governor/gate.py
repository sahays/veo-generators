"""Bounded FIFO admission gate with a max-concurrency limit (one per model).

`acquire` either takes a free slot or joins the tail of a bounded queue and blocks on its own
`threading.Event`; `release` hands the slot directly to the head waiter. Strict FIFO, O(1)
per hand-off, no thundering herd and no polling. A full queue or a wait longer than the
caller's budget raises `GovernorSaturated` instead of blocking forever.
"""

from __future__ import annotations

import threading
from collections import deque


class QueueFull(Exception):
    """The gate's waiting queue is at capacity."""


class FifoGate:
    def __init__(self, concurrency: int, capacity: int) -> None:
        self._limit, self._capacity = max(1, concurrency), max(1, capacity)
        self._active = 0
        self._waiters: deque[threading.Event] = deque()
        self._lock = threading.Lock()

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._waiters)

    def _enqueue(self) -> threading.Event | None:
        """None = slot taken immediately; else the event to wait on."""
        with self._lock:
            if self._active < self._limit and not self._waiters:
                self._active += 1
                return None
            if len(self._waiters) >= self._capacity:
                raise QueueFull(f"{len(self._waiters)} callers already queued")
            ticket = threading.Event()
            self._waiters.append(ticket)
            return ticket

    def acquire(self, timeout_s: float) -> bool:
        """True when a slot is held (caller must `release`); False on timeout."""
        ticket = self._enqueue()
        if ticket is None or ticket.wait(max(0.0, timeout_s)):
            return True
        with self._lock:
            if ticket.is_set():  # handed over between the timeout and the lock
                return True
            self._waiters.remove(ticket)  # rare path: O(queue) removal on timeout only
            return False

    def release(self) -> None:
        with self._lock:
            if self._waiters:
                self._waiters.popleft().set()  # slot passes to the head waiter
            else:
                self._active = max(0, self._active - 1)

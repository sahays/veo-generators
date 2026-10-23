"""Classify a provider exception: quota / transient / empty / fatal, plus any server retry hint.

Looks at structured fields first (`code`, `status`, `response.headers`, `details` as exposed by
`google.genai.errors.APIError` and `google.api_core` exceptions), walking the `__cause__` /
`__context__` chain, then falls back to status markers in the message. Fatal errors (4xx
other than 408/429, validation errors, ...) are never retried.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Final

import httpx

from .errors import EmptyModelResponse


class Kind(Enum):
    QUOTA = "quota"
    TRANSIENT = "transient"
    EMPTY = "empty"
    FATAL = "fatal"


@dataclass(frozen=True)
class Verdict:
    kind: Kind
    retry_after_s: float | None = None


_TRANSIENT_CODES: Final[frozenset[int]] = frozenset({408, 500, 502, 503, 504})
_QUOTA_STATUS: Final[frozenset[str]] = frozenset({"RESOURCE_EXHAUSTED"})
_TRANSIENT_STATUS: Final[frozenset[str]] = frozenset(
    {"UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}
)
_QUOTA_RE: Final[re.Pattern[str]] = re.compile(r"\b429\b|RESOURCE_EXHAUSTED")
_TRANSIENT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b50[0234]\b|UNAVAILABLE|DEADLINE_EXCEEDED"
)
_RETRY_DELAY_RE: Final[re.Pattern[str]] = re.compile(
    r"retry_?delay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE
)
_NETWORK_ERRORS: Final[tuple[type[BaseException], ...]] = (
    httpx.TransportError,
    ConnectionError,
    TimeoutError,
)
_MAX_CHAIN: Final[int] = 6


def _chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(seen) < _MAX_CHAIN:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def _kind_of(exc: BaseException) -> Kind | None:
    if isinstance(exc, EmptyModelResponse):
        return Kind.EMPTY
    code, status = _status_code(exc), str(getattr(exc, "status", "") or "").upper()
    if code == 429 or status in _QUOTA_STATUS:
        return Kind.QUOTA
    if code in _TRANSIENT_CODES or status in _TRANSIENT_STATUS:
        return Kind.TRANSIENT
    if isinstance(exc, _NETWORK_ERRORS):
        return Kind.TRANSIENT
    return None


def _text_kind(text: str) -> Kind:
    if _QUOTA_RE.search(text):
        return Kind.QUOTA
    return Kind.TRANSIENT if _TRANSIENT_RE.search(text) else Kind.FATAL


def _header_delay(value: str) -> float | None:
    """`Retry-After` is delta-seconds or an HTTP date (RFC 9110 §10.2.3)."""
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _hint(exc: BaseException) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None)
    value = headers.get("retry-after") if headers is not None else None
    if isinstance(value, str) and (delay := _header_delay(value)) is not None:
        return delay
    found = _RETRY_DELAY_RE.search(f"{getattr(exc, 'details', '')} {exc}")
    return float(found.group(1)) if found else None


def retry_after_s(exc: BaseException) -> float | None:
    """Server-requested delay (Retry-After header or RetryInfo.retryDelay), if any."""
    return next((h for e in _chain(exc) if (h := _hint(e)) is not None), None)


def classify(exc: BaseException) -> Verdict:
    links = list(_chain(exc))
    kind = next((k for e in links if (k := _kind_of(e)) is not None), None)
    if kind is None:
        kind = _text_kind(" | ".join(str(e) for e in links))
    return Verdict(kind, retry_after_s(exc) if kind is not Kind.FATAL else None)

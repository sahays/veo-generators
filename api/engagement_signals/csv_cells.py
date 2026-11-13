"""Cell-level parsing for engagement CSV files: headers, numbers, dates and times.

Pure functions, no I/O. Every parser returns None for text it cannot read so the
caller can count and skip the row.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from functools import lru_cache

SECONDS_PER_DAY = 86400.0

# Day-first formats come before month-first: BARC exports are dd/mm/yyyy.
_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%b-%y",
    "%d/%m/%y",
    "%Y%m%d",
    "%d %B %Y",
    "%b %d, %Y",
    "%m/%d/%Y",
)
_HEADER_JUNK_RE: re.Pattern[str] = re.compile(r"[^a-z0-9]+")
_NUMBER_JUNK_RE: re.Pattern[str] = re.compile(r"[,%\s\u00a0]")
_CLOCK_RE: re.Pattern[str] = re.compile(
    r"^(\d+):(\d{1,2})(?::(\d{1,2}))?([.,]\d+)?\s*(am|pm)?$", re.IGNORECASE
)
_DATETIME_RE: re.Pattern[str] = re.compile(r"^(\S+?)(?:T|\s+)(\d{1,2}:\d{2}.*?)Z?$")


def normalise_header(name: str) -> str:
    """Lowercase a header and collapse punctuation: `TVR (%)` -> `tvr`."""
    return _HEADER_JUNK_RE.sub(" ", name.replace("\ufeff", "").lower()).strip()


def parse_number(cell: str) -> float | None:
    """Parse a metric cell, ignoring `%`, thousands separators and spaces."""
    text = _NUMBER_JUNK_RE.sub("", cell)
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


@lru_cache(maxsize=1024)
def parse_date(cell: str) -> int | None:
    """Parse a calendar date to its ordinal day number (cached per distinct text)."""
    text = cell.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).toordinal()
        except ValueError:
            continue
    return None


def _clock_seconds(text: str, two_part_is_hours: bool) -> float | None:
    """Parse `mm:ss`, `hh:mm` or `hh:mm:ss[.ms]` (optionally am/pm) to seconds."""
    match = _CLOCK_RE.match(text)
    if match is None:
        return None
    first, second, third, fraction, meridiem = match.groups()
    frac = float(fraction.replace(",", ".")) if fraction else 0.0
    if third is None and not (two_part_is_hours or meridiem):
        minutes, seconds = int(first), int(second)
        return minutes * 60.0 + seconds + frac if seconds < 60 else None
    hours, minutes, seconds = int(first), int(second), int(third or 0)
    if minutes >= 60 or seconds >= 60:
        return None
    if meridiem:
        hours = hours % 12 + (12 if meridiem.lower() == "pm" else 0)
    return hours * 3600.0 + minutes * 60.0 + seconds + frac


def parse_time_cell(
    cell: str, unit_scale: float = 1.0, wall_clock: bool = False
) -> tuple[float, bool] | None:
    """Parse a time cell to `(seconds, has_date)`.

    Accepts plain numbers (multiplied by `unit_scale`), `mm:ss`, `hh:mm:ss[.ms]`
    and `date time` / ISO date-times. A two-part value is `mm:ss` unless
    `wall_clock` is set, when it is a clock time `hh:mm`. With a date, the result
    counts seconds from day ordinal 0 so rows on different days order correctly.
    """
    text = cell.strip()
    if not text:
        return None
    if ":" not in text:
        number = parse_number(text)
        return None if number is None else (number * unit_scale, False)
    stamped = _DATETIME_RE.match(text)
    if stamped is None:
        seconds = _clock_seconds(text, two_part_is_hours=wall_clock)
        return None if seconds is None else (seconds, False)
    day = parse_date(stamped.group(1))
    seconds = _clock_seconds(stamped.group(2).strip(), two_part_is_hours=True)
    if day is None or seconds is None:
        return None
    return day * SECONDS_PER_DAY + seconds, True

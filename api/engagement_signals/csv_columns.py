"""Column-role resolution for engagement CSV files.

Decides which column is the time axis, which are date / end-time / duration helpers
(never metrics) and which may be metrics, from normalised header text. Pure, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from csv_cells import normalise_header

# Exact normalised headers accepted as the time column, best first.
_TIME_PRIORITY: tuple[str, ...] = (
    "datetime",
    "date time",
    "start time",
    "starttime",
    "start",
    "timestamp",
    "time",
    "time sec",
    "time s",
    "seconds",
    "second",
    "secs",
    "sec",
    "t",
    "minutes",
    "minute",
    "mins",
    "min",
)
_TIME_RANK: dict[str, int] = {name: rank for rank, name in enumerate(_TIME_PRIORITY)}
_TIME_TOKENS: frozenset[str] = frozenset({"time", "timestamp", "datetime"})
_NOT_TIME_TOKENS: frozenset[str] = frozenset({"spent", "watched", "viewed", "share"})
_END_TOKENS: frozenset[str] = frozenset({"end", "endtime", "stop", "finish"})
_DURATION_TOKENS: frozenset[str] = frozenset({"duration", "dur", "length"})
_DATE_NAMES: frozenset[str] = frozenset({"date", "dt"})
_ID_TOKENS: frozenset[str] = frozenset({"week", "month", "year", "id", "index"})
_UNIT_SCALES: tuple[tuple[frozenset[str], float], ...] = (
    (frozenset({"minutes", "minute", "mins", "min"}), 60.0),
    (frozenset({"ms", "msec", "millis", "milliseconds"}), 0.001),
    (frozenset({"hours", "hour", "hrs", "hr"}), 3600.0),
)
# Token priority for choosing the primary metric, best first.
_METRIC_PRIORITY: tuple[str, ...] = (
    "tvr",
    "rating",
    "ratings",
    "engagement",
    "score",
    "value",
    "retention",
    "impressions",
    "reach",
    "viewers",
    "views",
    "audience",
)
_METRIC_RANK: dict[str, int] = {
    name: rank for rank, name in enumerate(_METRIC_PRIORITY)
}


@dataclass(frozen=True)
class ColumnRoles:
    """Indices of the columns that play a part in parsing."""

    time: int
    date: int | None
    end: int | None
    metric_candidates: tuple[int, ...]
    forced_metric: int | None
    unit_scale: float
    wall_clock: bool


def _time_rank(norm: str) -> int | None:
    """Rank a header as a time column (lower is better) or None if it is not one."""
    tokens = set(norm.split())
    if tokens & (_END_TOKENS | _DURATION_TOKENS):
        return None
    if norm in _TIME_RANK:
        return _TIME_RANK[norm]
    if tokens & _TIME_TOKENS and not tokens & _NOT_TIME_TOKENS:
        return len(_TIME_PRIORITY) + (0 if "start" in tokens else 1)
    return None


def _is_date(norm: str) -> bool:
    """True for a calendar-date column that carries no time of day."""
    tokens = set(norm.split())
    return norm in _DATE_NAMES or ("date" in tokens and not tokens & _TIME_TOKENS)


def _first_with(norms: list[str], wanted: frozenset[str]) -> int | None:
    """Index of the first header containing any of the `wanted` tokens."""
    for idx, norm in enumerate(norms):
        if wanted & set(norm.split()):
            return idx
    return None


def _find_named(headers: list[str], norms: list[str], name: str, role: str) -> int:
    """Resolve a user-chosen column by exact or normalised name, or raise."""
    lowered = [h.strip().lower() for h in headers]
    target = name.strip().lower()
    if target in lowered:
        return lowered.index(target)
    norm_target = normalise_header(name)
    if norm_target and norm_target in norms:
        return norms.index(norm_target)
    available = ", ".join(headers)
    raise ValueError(
        f"The {role} column '{name}' was not found. Available columns: {available}."
    )


def find_time_column(headers: list[str]) -> int | None:
    """Index of the best time column by priority, or None when there is none."""
    ranked = [
        (rank, idx)
        for idx, header in enumerate(headers)
        if (rank := _time_rank(normalise_header(header))) is not None
    ]
    return min(ranked)[1] if ranked else None


def metric_sort_key(header: str, position: int) -> tuple[int, int]:
    """Sort key placing preferred metrics (TVR, rating, ...) first, then file order."""
    tokens = normalise_header(header).split()
    rank = min(
        (_METRIC_RANK.get(tok, len(_METRIC_PRIORITY)) for tok in tokens), default=0
    )
    return rank, position


def _unit_scale(norm: str) -> float:
    """Seconds per unit implied by the time header (`minute` -> 60)."""
    tokens = set(norm.split())
    return next((scale for names, scale in _UNIT_SCALES if names & tokens), 1.0)


def resolve_roles(
    headers: list[str], time_column: str | None = None, metric: str | None = None
) -> ColumnRoles:
    """Assign column roles, honouring explicit `time_column` / `metric` overrides.

    Raises `ValueError` when no time column can be found or an override names a
    column that does not exist.
    """
    norms = [normalise_header(h) for h in headers]
    if time_column:
        time_idx: int | None = _find_named(headers, norms, time_column, "time")
    else:
        time_idx = find_time_column(headers)
    if time_idx is None:
        raise ValueError(
            "No time column was found (expected e.g. 'Start Time', 'time' or "
            f"'seconds'). Columns in the file: {', '.join(headers)}."
        )
    forced = _find_named(headers, norms, metric, "metric") if metric else None
    if forced == time_idx:
        raise ValueError("The metric column must differ from the time column.")
    date_idx = next(
        (i for i, n in enumerate(norms) if _is_date(n) and i != time_idx), None
    )
    end_idx = _first_with(norms, _END_TOKENS)
    helpers = {time_idx, date_idx, end_idx}
    candidates = tuple(
        idx
        for idx, norm in enumerate(norms)
        if idx == forced
        or not (
            idx in helpers
            or _time_rank(norm) is not None
            or _is_date(norm)
            or set(norm.split()) & (_END_TOKENS | _DURATION_TOKENS | _ID_TOKENS)
        )
    )
    time_tokens = set(norms[time_idx].split())
    return ColumnRoles(
        time=time_idx,
        date=date_idx,
        end=end_idx if end_idx != time_idx else None,
        metric_candidates=candidates,
        forced_metric=forced,
        unit_scale=_unit_scale(norms[time_idx]),
        wall_clock=date_idx is not None
        or end_idx is not None
        or "start" in time_tokens,
    )

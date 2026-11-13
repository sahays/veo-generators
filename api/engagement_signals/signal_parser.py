"""Parse engagement CSV files (BARC minute-level exports or generic `time,value`).

Pure: bytes in, `SignalSeries` out. Times end up as seconds from the start of the
video: wall-clock layouts are measured from their first row, then `offset_sec` is
added to every row. Unreadable rows are skipped and reported in `warnings`.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from statistics import median

from csv_cells import SECONDS_PER_DAY, parse_date, parse_number, parse_time_cell
from csv_columns import ColumnRoles, find_time_column, metric_sort_key, resolve_roles
from engagement_series import Point, SignalSeries

MAX_SIGNAL_ROWS = 200_000
_HEADER_SCAN_ROWS = 25
_SAMPLE_ROWS = 5
_DATE_PROBE_ROWS = 20
_SNIFF_CHARS = 8192
_DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")
_HALF_DAY = SECONDS_PER_DAY / 2


@dataclass
class _Table:
    """Decoded CSV: unique header labels plus the non-blank data rows."""

    headers: list[str]
    rows: list[list[str]]


def _decode(content: bytes) -> str:
    """Decode CSV bytes (UTF-8 with or without BOM, UTF-16 with BOM, or cp1252)."""
    if not content.strip():
        raise ValueError("The CSV file is empty.")
    has_utf16_bom = content[:2] in (b"\xff\xfe", b"\xfe\xff")
    for encoding in ("utf-16",) if has_utf16_bom else ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    raise ValueError("The file is not readable text. Export it as a UTF-8 CSV.")


def _read_rows(text: str) -> list[list[str]]:
    """Split text into stripped, non-blank rows, stopping past the row cap."""
    lines = [ln for ln in text[:_SNIFF_CHARS].splitlines() if ln.strip()]
    sample = "\n".join(lines[:_SAMPLE_ROWS])
    delimiter = max(_DELIMITERS, key=sample.count)
    rows: list[list[str]] = []
    try:
        for raw in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            cells = [cell.strip() for cell in raw]
            if any(cells):
                rows.append(cells)
            if len(rows) > MAX_SIGNAL_ROWS + _HEADER_SCAN_ROWS:
                break
    except csv.Error as err:
        raise ValueError("The file could not be parsed as CSV.") from err
    return rows


def _unique_headers(cells: list[str]) -> list[str]:
    """Label every column: blanks become `column N`, repeats get a numeric suffix."""
    seen: dict[str, int] = {}
    labels: list[str] = []
    for position, cell in enumerate(cells, start=1):
        label = cell.replace("\ufeff", "").strip() or f"column {position}"
        seen[label] = seen.get(label, 0) + 1
        labels.append(label if seen[label] == 1 else f"{label} ({seen[label]})")
    return labels


def _header_position(rows: list[list[str]], time_column: str | None) -> int:
    """Index of the header row: the first early row that names a time column."""
    wanted = time_column.strip().lower() if time_column else None
    for position, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        if wanted is not None and wanted in (cell.lower() for cell in row):
            return position
        if wanted is None and len(row) > 1 and find_time_column(row) is not None:
            return position
    return 0


def _read_table(content: bytes, time_column: str | None) -> _Table:
    """Decode and split the file, enforcing the row cap."""
    rows = _read_rows(_decode(content))
    start = _header_position(rows, time_column)
    data = rows[start + 1 :]
    if not data:
        raise ValueError("The CSV file has a header but no data rows.")
    if len(data) > MAX_SIGNAL_ROWS:
        raise ValueError(
            f"The CSV file has more than {MAX_SIGNAL_ROWS:,} rows; "
            "export a shorter range or a coarser interval."
        )
    return _Table(headers=_unique_headers(rows[start]), rows=data)


def _cell(row: list[str], index: int | None) -> str:
    """Cell at `index`, or an empty string when the row is short."""
    return row[index] if index is not None and index < len(row) else ""


def _time_of(
    row: list[str], index: int | None, roles: ColumnRoles
) -> tuple[float, bool] | None:
    """Parse the time cell at `index` under the file's unit and clock convention."""
    return parse_time_cell(_cell(row, index), roles.unit_scale, roles.wall_clock)


def _usable_date_column(table: _Table, roles: ColumnRoles) -> int | None:
    """Date column index if its first rows hold readable dates, else None."""
    if roles.date is None:
        return None
    probe = table.rows[:_DATE_PROBE_ROWS]
    readable = any(parse_date(_cell(row, roles.date)) is not None for row in probe)
    return roles.date if readable else None


def _absolute_times(
    table: _Table, roles: ColumnRoles, date_idx: int | None
) -> tuple[list[float | None], bool]:
    """Per-row time in seconds (None if unreadable) and whether rows carry dates."""
    times: list[float | None] = []
    dated = date_idx is not None
    for row in table.rows:
        parsed = _time_of(row, roles.time, roles)
        if parsed is None:
            times.append(None)
            continue
        seconds, has_date = parsed
        dated = dated or has_date
        if date_idx is not None and not has_date:
            day = parse_date(_cell(row, date_idx))
            times.append(None if day is None else day * SECONDS_PER_DAY + seconds)
        else:
            times.append(seconds)
    return times, dated


def _unwrap_midnight(times: list[float | None]) -> int:
    """Add a day after each backward jump of over 12 h, in place; return the count."""
    carry, wraps, previous = 0.0, 0, None
    for position, value in enumerate(times):
        if value is None:
            continue
        if previous is not None and value + carry < previous - _HALF_DAY:
            carry += SECONDS_PER_DAY
            wraps += 1
        previous = value + carry
        times[position] = previous
    return wraps


def _numeric_columns(
    table: _Table, roles: ColumnRoles, keep: list[int]
) -> dict[int, list[float | None]]:
    """Parse candidate metric columns for the kept rows; drop mostly-text columns."""
    needed = max(1, (len(keep) + 1) // 2)
    columns: dict[int, list[float | None]] = {}
    for index in roles.metric_candidates:
        values = [parse_number(_cell(table.rows[r], index)) for r in keep]
        filled = len(values) - values.count(None)
        if filled >= needed or (index == roles.forced_metric and filled):
            columns[index] = values
    return columns


def _ordered_rows(times: list[float | None]) -> tuple[list[int], int]:
    """Row indices ordered by time with repeats removed, plus the repeat count."""
    order = sorted((t, i) for i, t in enumerate(times) if t is not None)
    keep: list[int] = []
    last: float | None = None
    for when, index in order:
        if when != last:
            keep.append(index)
        last = when
    return keep, len(order) - len(keep)


def _fallback_interval(table: _Table, roles: ColumnRoles, row: int) -> float:
    """Interval for a single-row file: end minus start when present, else 1 s."""
    start = _time_of(table.rows[row], roles.time, roles)
    end = _time_of(table.rows[row], roles.end, roles)
    if start is None or end is None:
        return 1.0
    span = (end[0] - start[0]) % SECONDS_PER_DAY
    return span if span > 0 else 1.0


def _gap_warning(points: list[Point], interval: float) -> list[str]:
    """Warn when samples are missing (spacing well above the interval)."""
    gaps = sum(1 for a, b in zip(points, points[1:]) if b[0] - a[0] > 1.5 * interval)
    if not gaps:
        return []
    return [f"The signal has {gaps} gap(s) longer than the sample interval."]


@dataclass
class _Timeline:
    """Kept rows in time order with their final timestamps and parse notes."""

    keep: list[int]
    stamps: list[float]
    warnings: list[str]
    unreadable: int


def _align_rows(table: _Table, roles: ColumnRoles, offset_sec: float) -> _Timeline:
    """Order rows by time and convert to seconds from video start (+ offset)."""
    warnings: list[str] = []
    date_idx = _usable_date_column(table, roles)
    if roles.date is not None and date_idx is None:
        name = table.headers[roles.date]
        warnings.append(f"Dates in '{name}' could not be read; ordered by time only.")
    times, dated = _absolute_times(table, roles, date_idx)
    first = next((i for i, t in enumerate(times) if t is not None), 0)
    clock_text = ":" in _cell(table.rows[first], roles.time)
    # Plain numbers are already seconds on the video's clock: never re-anchored.
    wall_clock = dated or (roles.wall_clock and clock_text)
    if wall_clock and not dated and _unwrap_midnight(times):
        warnings.append("No date column: assumed the broadcast crosses midnight.")
    keep, repeats = _ordered_rows(times)
    if repeats:
        warnings.append(f"Ignored {repeats} row(s) repeating an earlier timestamp.")
    if not keep:
        raise ValueError(
            f"No readable times in column '{table.headers[roles.time]}'. "
            "Use seconds, mm:ss or hh:mm:ss."
        )
    base = times[keep[0]] if wall_clock else 0.0
    shift = offset_sec - (base or 0.0)
    stamps = [round((times[i] or 0.0) + shift, 3) for i in keep]
    early = sum(1 for stamp in stamps if stamp < 0)
    if early:
        warnings.append(
            f"Dropped {early} row(s) that fall before the start of the video "
            "after applying the offset."
        )
    return _Timeline(
        keep=keep[early:],
        stamps=stamps[early:],
        warnings=warnings,
        unreadable=len(times) - len(keep) - repeats,
    )


def _pick_primary(
    table: _Table, roles: ColumnRoles, columns: dict[int, list[float | None]]
) -> list[int]:
    """Metric column indices, primary first, or raise when none is numeric."""
    if roles.forced_metric is not None and roles.forced_metric not in columns:
        name = table.headers[roles.forced_metric]
        raise ValueError(f"The metric column '{name}' has no numeric values.")
    if not columns:
        raise ValueError(
            "No numeric metric column was found. "
            f"Columns in the file: {', '.join(table.headers)}."
        )
    ordered = sorted(columns, key=lambda i: metric_sort_key(table.headers[i], i))
    if roles.forced_metric is not None:
        ordered.remove(roles.forced_metric)
        ordered.insert(0, roles.forced_metric)
    return ordered


def _parse_table(
    table: _Table, time_column: str | None, metric: str | None, offset_sec: float
) -> SignalSeries:
    """Turn a decoded table into a `SignalSeries`."""
    roles = resolve_roles(table.headers, time_column, metric)
    rows = _align_rows(table, roles, offset_sec)
    if not rows.keep:
        raise ValueError("Every row falls before the start of the video.")
    columns = _numeric_columns(table, roles, rows.keep)
    ordered = _pick_primary(table, roles, columns)
    metrics: dict[str, list[Point]] = {
        table.headers[index]: [
            (t, v) for t, v in zip(rows.stamps, columns[index]) if v is not None
        ]
        for index in ordered
    }
    primary = table.headers[ordered[0]]
    points = metrics[primary]
    warnings = rows.warnings
    skipped = rows.unreadable + len(rows.keep) - len(points)
    if skipped:
        warnings.append(
            f"Skipped {skipped} row(s) with an unreadable time or '{primary}' value."
        )
    if len(points) > 1:
        interval = float(median(b[0] - a[0] for a, b in zip(points, points[1:])))
    else:
        interval = _fallback_interval(table, roles, rows.keep[0])
    interval = interval if interval > 0 else 1.0
    return SignalSeries(
        metrics=metrics,
        primary_metric=primary,
        interval_sec=round(interval, 3),
        duration_sec=round(points[-1][0] + interval, 3),
        time_column=table.headers[roles.time],
        warnings=warnings + _gap_warning(points, interval),
    )


def parse_signal_csv(
    content: bytes,
    time_column: str | None = None,
    metric: str | None = None,
    offset_sec: float = 0.0,
) -> SignalSeries:
    """Parse an engagement CSV into a `SignalSeries`.

    `time_column` and `metric` override automatic column choice. `offset_sec` is
    added to every timestamp; rows that land before 0 are dropped with a warning.
    Raises `ValueError` (with a user-readable message) for empty or undecodable
    input, more than 200 000 rows, or when no time or metric column is usable.
    """
    table = _read_table(content, time_column)
    return _parse_table(table, time_column, metric, offset_sec)


def preview_signal_csv(content: bytes, filename: str) -> dict:
    """Describe a CSV as a `SignalPreview` dict using automatic column choice.

    Unusable files (empty, undecodable, over the row cap) raise `ValueError`.
    A readable file whose columns cannot be mapped still returns a preview, with
    `time_column` / `primary_metric` set to None and the reason in `warnings`.
    """
    table = _read_table(content, None)
    width = len(table.headers)
    preview: dict = {
        "filename": filename,
        "row_count": len(table.rows),
        "columns": list(table.headers),
        "sample_rows": [
            dict(zip(table.headers, (row + [""] * width)[:width]))
            for row in table.rows[:_SAMPLE_ROWS]
        ],
    }
    try:
        series = _parse_table(table, None, None, 0.0)
    except ValueError as err:
        guess = find_time_column(table.headers)
        return {
            **preview,
            "time_column": None if guess is None else table.headers[guess],
            "metrics": [],
            "primary_metric": None,
            "duration_sec": 0.0,
            "interval_sec": 0.0,
            "warnings": [str(err)],
        }
    return {
        **preview,
        "time_column": series.time_column,
        "metrics": list(series.metrics),
        "primary_metric": series.primary_metric,
        "duration_sec": series.duration_sec,
        "interval_sec": series.interval_sec,
        "warnings": list(series.warnings),
    }

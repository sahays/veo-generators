"""Engagement CSV parser: BARC layout, generic layout, alignment and error paths."""

from __future__ import annotations

import pytest
from signal_parser import MAX_SIGNAL_ROWS, parse_signal_csv, preview_signal_csv

_BARC_HEADER = (
    "Date,Start Time,End Time,Duration (Mins),Impressions ('000s),TVR (%),Reach ('000s)"
)


def _barc(*rows: str) -> bytes:
    return "\n".join([_BARC_HEADER, *rows]).encode("utf-8")


_BARC_EVENING = _barc(
    '01/03/2024,20:00:00,20:00:59,1,"1,234",0.42%,"2,001"',
    '01/03/2024,20:01:00,20:01:59,1,"1,300",0.47%,"2,050"',
    '01/03/2024,20:02:00,20:02:59,1,"1,180",0.39%,"1,990"',
)


def test_barc_export_maps_columns_and_measures_time_from_the_first_row() -> None:
    series = parse_signal_csv(_BARC_EVENING)
    assert series.time_column == "Start Time"
    assert series.primary_metric == "TVR (%)"
    assert list(series.metrics) == ["TVR (%)", "Impressions ('000s)", "Reach ('000s)"]
    assert series.points == [(0.0, 0.42), (60.0, 0.47), (120.0, 0.39)]
    assert series.metrics["Impressions ('000s)"][0] == (0.0, 1234.0)
    assert series.metrics["Reach ('000s)"][2] == (120.0, 1990.0)
    assert series.interval_sec == 60.0
    assert series.duration_sec == 180.0  # last row's start plus one interval
    assert series.warnings == []


def test_duration_end_time_and_date_columns_are_never_metrics() -> None:
    series = parse_signal_csv(_BARC_EVENING)
    assert not {"Duration (Mins)", "End Time", "Date", "Start Time"} & set(
        series.metrics
    )
    # Even when it is the only other numeric column, duration is not a metric.
    only_duration = b"Start Time,Duration (Mins)\n20:00:00,1\n20:01:00,1\n"
    with pytest.raises(ValueError, match="No numeric metric column"):
        parse_signal_csv(only_duration)


def test_broadcast_crossing_midnight_is_ordered_by_date_and_time() -> None:
    shuffled = _barc(
        "02/03/2024,00:00:00,00:00:59,1,30,0.30,3",
        "01/03/2024,23:58:00,23:58:59,1,10,0.10,1",
        "02/03/2024,00:01:00,00:01:59,1,40,0.40,4",
        "01/03/2024,23:59:00,23:59:59,1,20,0.20,2",
    )
    series = parse_signal_csv(shuffled)
    assert series.points == [(0.0, 0.1), (60.0, 0.2), (120.0, 0.3), (180.0, 0.4)]
    assert series.duration_sec == 240.0
    assert series.warnings == []


def test_midnight_crossing_without_a_date_column_is_unwrapped_with_a_warning() -> None:
    content = b"Start Time,TVR\n23:59:00,1\n00:00:00,2\n00:01:00,3\n"
    series = parse_signal_csv(content)
    assert series.points == [(0.0, 1.0), (60.0, 2.0), (120.0, 3.0)]
    assert any("midnight" in warning for warning in series.warnings)


def test_two_part_times_are_clock_times_only_in_wall_clock_layouts() -> None:
    barc = parse_signal_csv(b"Start Time,TVR\n20:00,1\n20:01,2\n20:02,3\n")
    assert barc.points == [(0.0, 1.0), (60.0, 2.0), (120.0, 3.0)]  # hh:mm
    generic = parse_signal_csv(b"time,value\n20:00,1\n20:01,2\n20:02,3\n")
    assert [t for t, _ in generic.points] == [1200.0, 1201.0, 1202.0]  # mm:ss
    stamped = parse_signal_csv(
        b"timestamp,value\n2024-03-01 23:59:30,1\n2024-03-02T00:00:30Z,2\n"
    )
    assert stamped.points == [(0.0, 1.0), (60.0, 2.0)]
    minutes = parse_signal_csv(b"Minute,Rating\n0,4\n1,5\n2.5,6\n")
    assert [t for t, _ in minutes.points] == [0.0, 60.0, 150.0]
    # Numeric start/end columns are seconds of video time, not a wall clock.
    numeric = parse_signal_csv(b"start,end,value\n30,40,5\n40,50,6\n")
    assert numeric.points == [(30.0, 5.0), (40.0, 6.0)]
    assert list(numeric.metrics) == ["value"]


def test_end_time_is_never_chosen_as_the_time_axis() -> None:
    content = b"End Time,Elapsed Time,TVR\n00:01:00,00:00:00,1\n00:02:00,00:01:00,2\n"
    series = parse_signal_csv(content)
    assert series.time_column == "Elapsed Time"
    assert [t for t, _ in series.points] == [0.0, 60.0]
    with pytest.raises(ValueError, match="No time column was found"):
        parse_signal_csv(b"End Time,Duration,TVR\n00:01:00,60,1\n00:02:00,60,2\n")


def test_offset_shifts_every_row_and_drops_rows_before_zero() -> None:
    later = parse_signal_csv(_BARC_EVENING, offset_sec=30.0)
    assert [t for t, _ in later.points] == [30.0, 90.0, 150.0]
    assert later.duration_sec == 210.0
    assert later.warnings == []

    earlier = parse_signal_csv(_BARC_EVENING, offset_sec=-90.0)
    assert earlier.points == [(30.0, 0.39)]
    assert any(
        "Dropped 2 row(s)" in w and "before the start" in w for w in earlier.warnings
    )
    with pytest.raises(ValueError, match="before the start of the video"):
        parse_signal_csv(_BARC_EVENING, offset_sec=-1000.0)


@pytest.mark.parametrize(
    ("body", "times"),
    [
        ("0,5\n10,6\n20,7\n", [0.0, 10.0, 20.0]),
        ("00:10,5\n00:20,6\n01:30,7\n", [10.0, 20.0, 90.0]),
        ("00:00:05.5,5\n00:01:05.5,6\n01:00:00,7\n", [5.5, 65.5, 3600.0]),
        ("12.5,5\n13.0,6\n13.5,7\n", [12.5, 13.0, 13.5]),
    ],
)
def test_generic_time_value_files_keep_their_own_time_origin(
    body: str, times: list[float]
) -> None:
    """No "first row is t=0" guess: a generic file starting at 10 s stays at 10 s."""
    series = parse_signal_csv(("time,value\n" + body).encode())
    assert [t for t, _ in series.points] == times
    assert [v for _, v in series.points] == [5.0, 6.0, 7.0]
    assert series.time_column == "time"
    assert series.primary_metric == "value"


def test_bom_padding_and_header_case_are_normalised() -> None:
    content = b"\xef\xbb\xbf  TIME (s) ; Rating \n0;3,5\n5;4,5\n"
    series = parse_signal_csv(content)
    assert series.time_column == "TIME (s)"
    assert series.primary_metric == "Rating"
    assert [t for t, _ in series.points] == [0.0, 5.0]
    utf16 = "time,value\n0,1\n1,2\n".encode("utf-16")
    assert parse_signal_csv(utf16).points == [(0.0, 1.0), (1.0, 2.0)]


def test_title_rows_above_the_header_are_skipped() -> None:
    content = b"BARC India,Week 9\nChannel: Demo TV\n\n" + _BARC_EVENING
    series = parse_signal_csv(content)
    assert series.time_column == "Start Time"
    assert len(series.points) == 3


def test_explicit_overrides_beat_the_priority_lists() -> None:
    content = b"clock,time,TVR (%),Reach\n100,0,0.5,900\n160,60,0.6,950\n"
    default = parse_signal_csv(content)
    assert (default.time_column, default.primary_metric) == ("time", "TVR (%)")
    assert list(default.metrics) == ["TVR (%)", "Reach", "clock"]

    chosen = parse_signal_csv(content, time_column="clock", metric="reach")
    assert chosen.time_column == "clock"
    assert chosen.primary_metric == "Reach"
    assert chosen.points == [(100.0, 900.0), (160.0, 950.0)]
    assert "time" not in chosen.metrics

    with pytest.raises(ValueError, match="time column 'elapsed' was not found"):
        parse_signal_csv(content, time_column="elapsed")
    with pytest.raises(ValueError, match="metric column 'share' was not found"):
        parse_signal_csv(content, metric="share")
    with pytest.raises(ValueError, match="must differ from the time column"):
        parse_signal_csv(content, time_column="time", metric="time")


def test_unreadable_and_repeated_rows_are_skipped_and_counted() -> None:
    content = (
        b"time,value\n0,10\nn/a,11\n10,\n20,12\n20,99\n30,abc\n40,14\nSource: demo,\n"
    )
    series = parse_signal_csv(content)
    assert series.points == [(0.0, 10.0), (20.0, 12.0), (40.0, 14.0)]
    assert any(w.startswith("Skipped 4 row(s)") for w in series.warnings)
    assert any(w.startswith("Ignored 1 row(s) repeating") for w in series.warnings)
    assert series.interval_sec == 20.0
    assert series.duration_sec == 60.0


def test_interval_is_the_median_spacing_and_gaps_are_reported() -> None:
    content = b"time,value\n0,1\n30,1\n90,1\n150,1\n630,1\n690,1\n"
    series = parse_signal_csv(content)
    assert series.interval_sec == 60.0  # spacings are 30, 60, 60, 480, 60
    assert series.duration_sec == 750.0
    assert series.warnings == [
        "The signal has 1 gap(s) longer than the sample interval."
    ]
    single = parse_signal_csv(b"Start Time,End Time,TVR\n20:00:00,20:05:00,1.5\n")
    assert (single.interval_sec, single.duration_sec) == (300.0, 300.0)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "empty"),
        (b"  \n \n", "empty"),
        (b"PK\x03\x04\x00\x00\x00\x08\x00binary\x00\x00", "not readable text"),
        (b"time,value\n", "no data rows"),
        (b"name,score\nalpha,1\nbeta,2\n", "No time column was found"),
        (b"time,comment\n0,good\n10,bad\n", "No numeric metric column"),
        (b"time,value\nsoon,1\nlater,2\n", "No readable times"),
    ],
)
def test_unusable_input_raises_a_clear_error(content: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_signal_csv(content)


def test_row_cap_is_enforced_at_exactly_200_000_rows() -> None:
    assert MAX_SIGNAL_ROWS == 200_000
    rows = "".join(f"{i},1\n" for i in range(MAX_SIGNAL_ROWS + 1))
    with pytest.raises(ValueError, match="more than 200,000 rows"):
        parse_signal_csv(("time,value\n" + rows).encode())
    at_cap = "time,value\n" + rows[: rows.rindex("\n", 0, -1) + 1]
    series = parse_signal_csv(at_cap.encode())
    assert len(series.points) == MAX_SIGNAL_ROWS
    assert series.duration_sec == float(MAX_SIGNAL_ROWS)


def test_preview_describes_the_mapping_with_string_sample_rows() -> None:
    rows = [
        f"01/03/2024,20:{m:02d}:00,20:{m:02d}:59,1,{m},0.{m:02d},5" for m in range(8)
    ]
    preview = preview_signal_csv(_barc(*rows), "evening.csv")
    assert set(preview) == {
        "filename",
        "row_count",
        "columns",
        "time_column",
        "metrics",
        "primary_metric",
        "duration_sec",
        "interval_sec",
        "sample_rows",
        "warnings",
    }
    assert preview["filename"] == "evening.csv"
    assert preview["row_count"] == 8
    assert preview["columns"] == _BARC_HEADER.split(",")
    assert preview["time_column"] == "Start Time"
    assert preview["primary_metric"] == "TVR (%)"
    assert preview["metrics"] == ["TVR (%)", "Impressions ('000s)", "Reach ('000s)"]
    assert (preview["interval_sec"], preview["duration_sec"]) == (60.0, 480.0)
    assert len(preview["sample_rows"]) == 5
    assert preview["sample_rows"][1] == {
        "Date": "01/03/2024",
        "Start Time": "20:01:00",
        "End Time": "20:01:59",
        "Duration (Mins)": "1",
        "Impressions ('000s)": "1",
        "TVR (%)": "0.01",
        "Reach ('000s)": "5",
    }


def test_preview_of_an_unmappable_file_reports_why_instead_of_raising() -> None:
    preview = preview_signal_csv(b"name,score\nalpha,1\nbeta,2\n", "odd.csv")
    assert preview["time_column"] is None
    assert preview["primary_metric"] is None
    assert preview["metrics"] == []
    assert preview["columns"] == ["name", "score"]
    assert preview["sample_rows"] == [
        {"name": "alpha", "score": "1"},
        {"name": "beta", "score": "2"},
    ]
    assert len(preview["warnings"]) == 1
    assert "No time column was found" in preview["warnings"][0]
    with pytest.raises(ValueError, match="empty"):
        preview_signal_csv(b"", "empty.csv")

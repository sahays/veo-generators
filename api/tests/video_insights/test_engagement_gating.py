"""EngagementProcessor dependency gate and job failures, driven by the worker's poll."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from insight_jobs.engagement_processor import EngagementProcessor
from insights_store import InsightsStoreMixin
from models import EngagementRecord
from models_insights import EngagementSignalSpec
from unified_worker import UnifiedWorker

CSV_PATH = "uploads/ratings.csv"
GOOD_CSV = b"Time,TVR\n00:00:00,1.0\n00:00:05,3.0\n00:00:10,2.0\n00:00:15,4.0\n"
WAITING = ("pending", "waiting", "Waiting for scene analysis")
MISSING = (
    "The scene analysis this report was built on no longer exists. "
    "Start a new engagement analysis."
)
FAILED = (
    "The scene analysis of this video failed, so the report could not be built. "
    "Retry the scene analysis, then retry this report."
)
ARCHIVED = (
    "The scene analysis of this video was archived before it finished, so it "
    "will not complete. Start a new engagement analysis."
)


def _poll() -> None:
    """One cycle of the real worker loop over the engagement processor."""
    UnifiedWorker([EngagementProcessor()])._poll_cycle()


def _state(env: SimpleNamespace, record_id: str) -> tuple[str, str, str]:
    job = env.job(record_id)
    return job.status, job.stage, job.stage_detail


# ── Dependency gate ──────────────────────────────────────────────────


def _seed_every_dependency_state(env: SimpleNamespace) -> None:
    env.add_analysis("sa-done")
    env.add_analysis("sa-done-archived", archived=True)
    env.add_analysis("sa-running", status="analyzing")
    env.add_analysis("sa-queued", status="pending")
    env.add_analysis("sa-failed", status="failed", error_message="ffprobe exploded")
    env.add_analysis("sa-shelved", status="pending", archived=True)
    for job_id, analysis_id in [
        ("en-ready", "sa-done"),
        ("en-ready-archived", "sa-done-archived"),
        ("en-waiting", "sa-running"),
        ("en-queued", "sa-queued"),
        ("en-failed", "sa-failed"),
        ("en-missing", "sa-deleted"),
        ("en-shelved", "sa-shelved"),
    ]:
        env.add_job(job_id, scene_analysis_id=analysis_id)
    env.add_job("en-busy", scene_analysis_id="sa-failed", status="processing")
    env.add_job("en-archived", scene_analysis_id="sa-failed", archived=True)


def test_only_jobs_whose_analysis_completed_are_handed_to_the_worker(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    _seed_every_dependency_state(env)
    ready = EngagementProcessor().get_pending_records()
    # A completed analysis is usable even after it was archived.
    assert [r.id for r in ready] == ["en-ready", "en-ready-archived"]
    assert _state(env, "en-waiting") == WAITING and _state(env, "en-queued") == WAITING
    for job_id, message in [
        ("en-failed", FAILED),
        ("en-missing", MISSING),
        ("en-shelved", ARCHIVED),
    ]:
        job = env.job(job_id)
        assert (job.status, job.error_message, job.stage) == ("failed", message, "")
        assert job.completedAt is not None
    # The analysis's own error text is not copied into the report's message.
    assert "ffprobe" not in env.job("en-failed").error_message
    # Jobs that are not pending, or are archived, are left alone whatever they link to.
    written = {record_id for record_id, _ in env.store.writes}
    assert written == {
        "en-waiting",
        "en-queued",
        "en-failed",
        "en-missing",
        "en-shelved",
    }
    assert env.job("en-busy").status == "processing"
    assert env.job("en-archived").status == "pending"
    # Seven pending jobs cost one list read, not one read each.
    assert (env.store.analysis_list_reads, env.store.analysis_gets) == (1, 0)


def test_a_waiting_job_is_written_once_however_often_it_is_polled(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1", status="analyzing")
    env.add_job("en-1")
    processor = EngagementProcessor()
    assert [processor.get_pending_records() for _ in range(3)] == [[], [], []]
    assert len(env.store.writes) == 1 and _state(env, "en-1") == WAITING
    assert env.store.analysis_list_reads == 3


def test_analyses_are_not_read_when_no_job_is_pending(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.add_job("en-1", status="completed")
    env.add_job("en-2", status="failed")
    assert EngagementProcessor().get_pending_records() == []
    assert (env.store.analysis_list_reads, env.store.writes) == (0, [])


def test_a_waiting_job_runs_on_the_poll_after_its_analysis_completes(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    analysis = env.add_analysis("sa-1", status="analyzing", timeline_gcs_uri=None)
    env.add_job("en-1")
    _poll()
    assert _state(env, "en-1") == WAITING and env.ai.calls == []
    assert not [p for p in env.storage.objects if p.startswith("engagement/")]
    done = {"status": "completed", "timeline_gcs_uri": env.timeline_uri}
    env.store.analyses["sa-1"] = analysis.model_copy(update=done)
    _poll()
    job = env.job()
    assert (job.status, job.stage, job.progress_pct) == ("completed", "", 100)
    assert job.headline == "The headline."
    assert "engagement/en-1/report.json" in env.storage.objects


# ── Failures the user can act on ─────────────────────────────────────


def _barc(**signal: Any) -> EngagementSignalSpec:
    return EngagementSignalSpec(
        kind="barc",
        upload_id="up-csv",
        csv_gcs_uri=f"gs://test-bucket/{CSV_PATH}",
        csv_filename="ratings.csv",
        **signal,
    )


@pytest.mark.parametrize(
    ("csv", "signal", "message"),
    [
        (
            GOOD_CSV,
            {"offset_sec": 500.0},
            "The engagement signal has no samples inside the video's duration; "
            "check the alignment offset.",
        ),
        (
            b"Time,Note\n00:00:00,intro\n00:00:05,song\n",
            {},
            "No numeric metric column was found. Columns in the file: Time, Note.",
        ),
        (b"", {}, "The CSV file is empty."),
        (
            None,
            {},
            "The signal CSV could not be downloaded. It may have been deleted "
            "from Files.",
        ),
        (
            b"Time,TVR\n" + b"00:00:00,1.0\n" * 900_000,
            {},
            "The CSV file is larger than the 10 MB limit.",
        ),
    ],
)
def test_a_bad_signal_fails_the_job_with_a_message_for_the_user(
    engagement_env: SimpleNamespace, csv: Any, signal: dict[str, Any], message: str
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    if csv is not None:
        env.storage.objects[CSV_PATH] = csv
    env.add_job("en-1", signal=_barc(**signal))
    _poll()
    job = env.job()
    assert (job.status, job.error_message) == ("failed", message)
    assert job.report_gcs_uri is None and job.completedAt is not None
    # Nothing was sent to the model for a signal that cannot be used.
    assert env.ai.calls == []
    # The failed job is not picked up again until it is retried.
    writes = len(env.store.writes)
    _poll()
    assert len(env.store.writes) == writes


def test_an_unreadable_timeline_fails_the_job_without_leaking_storage_errors(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    env.add_analysis("sa-1")
    env.storage.objects["scene_analysis/sa-1/timeline.json"] = b"<html>AccessDenied"
    env.add_job("en-1")
    _poll()
    job = env.job()
    assert (job.status, job.error_message) == (
        "failed",
        "The scene analysis timeline could not be read.",
    )
    assert env.ai.calls == []


# ── Store query behind the scene analysis delete guard ───────────────


class _Doc:
    def __init__(self, record: EngagementRecord) -> None:
        self._data = record.model_dump()

    def to_dict(self) -> dict[str, Any]:
        return self._data


class _Query:
    """Applies a single-field equality `FieldFilter` to in-memory documents."""

    def __init__(self, docs: list[_Doc]) -> None:
        self._docs = docs
        self.filters: list[tuple[str, str, Any]] = []

    def where(self, filter: Any) -> "_Query":
        self.filters.append((filter.field_path, filter.op_string, filter.value))
        return self

    def stream(self) -> Iterator[_Doc]:
        for doc in self._docs:
            if all(doc.to_dict().get(name) == value for name, _, value in self.filters):
                yield doc


def test_dependants_of_an_analysis_are_found_with_one_equality_filter(
    engagement_env: SimpleNamespace,
) -> None:
    env = engagement_env
    records = [
        env.add_job("en-1", scene_analysis_id="sa-1"),
        env.add_job("en-2", scene_analysis_id="sa-2"),
        env.add_job("en-3", scene_analysis_id="sa-1", archived=True, status="failed"),
    ]
    store = InsightsStoreMixin()
    store.engagements_collection = _Query([_Doc(r) for r in records])
    found = store.find_engagements_for_analysis("sa-1")
    # Archived and failed reports still depend on the analysis.
    assert [r.id for r in found] == ["en-1", "en-3"]
    assert store.engagements_collection.filters == [("scene_analysis_id", "==", "sa-1")]

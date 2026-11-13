"""StagedJobProcessor: stage order, progress, checkpoints, cleanup, usage."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import deps
from insight_jobs.staged_processor import (
    JobContext,
    Stage,
    StagedJobProcessor,
    sum_usage,
)
from models import UsageMetrics


class _Storage:
    """In-memory stand-in for the parts of StorageService the base class uses."""

    bucket_name = "test-bucket"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def upload_bytes(self, data: bytes, path: str, content_type: str = "") -> str:
        self.objects[path] = data
        return f"gs://{self.bucket_name}/{path}"

    def blob_exists(self, gcs_uri: str) -> bool:
        return gcs_uri.removeprefix(f"gs://{self.bucket_name}/") in self.objects

    def download_bytes(self, gcs_uri: str) -> bytes:
        return self.objects[gcs_uri.removeprefix(f"gs://{self.bucket_name}/")]


class _Job(StagedJobProcessor):
    """Three stages; `fail_in` makes the named stage raise."""

    record_prefix = "demo"
    stages = (Stage("fetch", 1), Stage("crunch", 8, "analyzing"), Stage("publish", 1))

    def __init__(self, fail_in: str = "") -> None:
        self.fail_in = fail_in
        self.ran: list[str] = []
        self.temp_paths: list[str] = []

    @property
    def name(self) -> str:
        return "demo"

    @property
    def firestore_update_method(self) -> str:
        return "update_demo"

    def get_pending_records(self) -> list:
        return []

    def run_stage(self, ctx: JobContext, stage: Stage) -> None:
        self.ran.append(stage.name)
        self.temp_paths.append(ctx.tmp.create(suffix=".bin"))
        if stage.name == self.fail_in:
            raise RuntimeError("boom")
        if stage.name == "crunch":
            self.report(ctx, 0.5, "halfway", item_count=3)
            self.add_usage(
                ctx, {"input_tokens": 10, "output_tokens": 2, "cost_usd": 0.5}
            )
            ctx.notes.append("captions unavailable")

    def completion_updates(self, ctx: JobContext) -> dict[str, Any]:
        return {"headline": "done"}


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    firestore, storage = MagicMock(), _Storage()
    monkeypatch.setattr(deps, "firestore_svc", firestore)
    monkeypatch.setattr(deps, "storage_svc", storage)
    return SimpleNamespace(firestore=firestore, storage=storage)


def _updates(services: SimpleNamespace) -> list[dict[str, Any]]:
    return [call.args[1] for call in services.firestore.update_demo.call_args_list]


def test_stages_run_in_order_and_report_stage_status_and_progress(
    services: SimpleNamespace,
) -> None:
    job = _Job()
    job.process(SimpleNamespace(id="rec-1"))
    assert job.ran == ["fetch", "crunch", "publish"]
    trail = [
        (u["status"], u["stage"], u["stage_detail"], u["progress_pct"])
        for u in _updates(services)
    ]
    assert trail == [
        ("processing", "fetch", "", 0),
        ("analyzing", "crunch", "", 10),
        ("analyzing", "crunch", "halfway", 50),
        ("processing", "publish", "", 90),
        ("completed", "", "captions unavailable", 100),
    ]
    assert _updates(services)[2]["item_count"] == 3


def test_completion_writes_usage_subclass_fields_and_timestamp(
    services: SimpleNamespace,
) -> None:
    _Job().process(SimpleNamespace(id="rec-1"))
    final = _updates(services)[-1]
    assert final["headline"] == "done"
    assert (final["usage"]["input_tokens"], final["usage"]["cost_usd"]) == (10, 0.5)
    assert "completedAt" in final


def test_failing_stage_stops_the_job_and_still_removes_temp_files(
    services: SimpleNamespace,
) -> None:
    job = _Job(fail_in="crunch")
    with pytest.raises(RuntimeError, match="boom"):
        job.process(SimpleNamespace(id="rec-1"))
    assert job.ran == ["fetch", "crunch"]
    assert all(u["status"] != "completed" for u in _updates(services))
    assert len(job.temp_paths) == 2
    assert not any(os.path.exists(path) for path in job.temp_paths)


def test_progress_is_weighted_monotonic_and_never_100_while_running() -> None:
    job = _Job()
    fetch, crunch, publish = job.stages
    points = [
        job.progress_pct(fetch, 0.0),
        job.progress_pct(fetch, 1.0),
        job.progress_pct(crunch, 0.25),
        job.progress_pct(crunch, 7.0),  # out-of-range fraction is clamped
        job.progress_pct(publish, 0.5),
        job.progress_pct(publish, 1.0),
    ]
    assert points == [0, 10, 30, 90, 95, 99]


def test_checkpoints_round_trip_under_the_record_prefix(
    services: SimpleNamespace,
) -> None:
    job = _Job()
    uri = job.save_checkpoint("rec-1", "windows/3", {"n": 3, "text": "नमस्ते"})
    assert uri == "gs://test-bucket/demo/rec-1/windows/3.json"
    assert job.load_checkpoint("rec-1", "windows/3") == {"n": 3, "text": "नमस्ते"}
    # Another record with a longer id shares no checkpoints with this one.
    assert job.load_checkpoint("rec-12", "windows/3") is None
    assert job.load_checkpoint("rec-1", "windows/4") is None


def test_corrupt_or_non_object_checkpoint_loads_as_missing(
    services: SimpleNamespace,
) -> None:
    job = _Job()
    services.storage.objects["demo/rec-1/bad.json"] = b'{"cut off": '
    services.storage.objects["demo/rec-1/list.json"] = b"[1, 2]"
    assert job.load_checkpoint("rec-1", "bad") is None
    assert job.load_checkpoint("rec-1", "list") is None


def test_storage_error_while_loading_a_checkpoint_is_not_fatal(
    services: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _down(gcs_uri: str) -> bool:
        raise ConnectionError("gcs unavailable")

    monkeypatch.setattr(services.storage, "blob_exists", _down)
    assert _Job().load_checkpoint("rec-1", "probe") is None


def test_sum_usage_adds_tokens_and_cost_and_keeps_the_model_name() -> None:
    first = UsageMetrics(
        input_tokens=100, output_tokens=10, cost_usd=0.25, model_name="m"
    )
    total = sum_usage(sum_usage(UsageMetrics(), first), first.model_dump())
    assert (total.input_tokens, total.output_tokens, total.cost_usd) == (200, 20, 0.5)
    assert total.model_name == "m"
    assert sum_usage(total, None) is total

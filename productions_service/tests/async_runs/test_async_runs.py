"""Async stage runs over HTTP: 202 + background execution, single-flight, live progress,
graceful vs hard outcomes, stale heartbeat -> interrupted, and an idempotent Resume.

The long stage is replaced by a controllable fake (`BlockingStage`) that reports progress
through `storygraph.progress` exactly like the real keyframe / render stages, so these tests
exercise the real router, claim transaction, executor, tracker and status endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from main import app
from run_wait import create_production, status, wait_until_idle
from services.jobs import entrypoints, executor
from services.jobs.liveness import utc_now
from services.runtime import get_graph_store, get_repo
from storygraph import progress
from storygraph.errors import GateBlocked
from storygraph.repo.keyframe_sets import KeyframeSetRepo
from storygraph.repo.stage_jobs import StageJobRepo
from storygraph.schema import Role
from storygraph.schemas.stage_job import StageJob

BASE = "/api/v1/productions"


class BlockingStage:
    """Stands in for `run_project_stage`: reports progress, then waits to be released."""

    def __init__(self) -> None:
        self.started, self.release = threading.Event(), threading.Event()
        self.calls: list[tuple[str, bool]] = []

    def __call__(
        self, pid: str, stage_id: str, force: bool, quality: str | None
    ) -> dict[str, Any]:
        self.calls.append((stage_id, force))
        progress.stage_started(pid, stage_id)
        progress.add_total(pid, 4, "frames")
        progress.advance(pid, 3, "shot_2")
        self.started.set()
        assert self.release.wait(10), "test never released the stage"
        return {}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def stage(monkeypatch: pytest.MonkeyPatch) -> BlockingStage:
    fake = BlockingStage()
    monkeypatch.setattr(entrypoints, "run_project_stage", fake)
    yield fake
    fake.release.set()


def _resume(client: TestClient, pid: str) -> Any:
    return client.post(f"{BASE}/{pid}/stages/S8_KEYFRAMES/run?force=false")


def test_run_is_accepted_at_once_and_reports_live_progress(
    client: TestClient, stage: BlockingStage
) -> None:
    pid = create_production(client)
    t0 = time.monotonic()
    res = _resume(client, pid)
    assert res.status_code == 202 and time.monotonic() - t0 < 2.0
    accepted = res.json()
    assert (
        accepted["accepted"] is True and accepted["run"]["label"] == "Resume keyframes"
    )
    assert stage.started.wait(5)
    executor._tracker.flush()  # the ticker would do this within `tick_s`
    live = status(client, pid)["active_run"]
    assert live["run_id"] == accepted["stage_run_id"] and live["status"] == "running"
    assert live["stage"] == "S8_KEYFRAMES"
    assert live["progress"] == {
        "done": 3,
        "total": 4,
        "unit": "frames",
        "current": "shot_2",
    }
    stage.release.set()
    final = wait_until_idle(client, pid)
    assert (
        final["last_run"]["status"] == "completed" and final["last_run"]["finished_at"]
    )


def test_second_run_is_rejected_while_one_is_live_then_allowed(
    client: TestClient, stage: BlockingStage
) -> None:
    pid = create_production(client)
    first = _resume(client, pid).json()
    assert stage.started.wait(5)
    second = client.post(f"{BASE}/{pid}/stages/S9_QA/run")
    assert second.status_code == 409
    assert first["stage_run_id"] in second.json()["detail"]
    assert stage.calls == [("S8_KEYFRAMES", False)]  # the rejected run never executed
    stage.release.set()
    wait_until_idle(client, pid)
    assert client.post(f"{BASE}/{pid}/stages/S9_QA/run").status_code == 202
    wait_until_idle(client, pid)


def _gate_blocked(
    pid: str, stage_id: str, force: bool, quality: str | None
) -> dict[str, Any]:
    try:  # mirrors productions_service.run_project_stage's HTTP mapping
        raise GateBlocked("G2")
    except GateBlocked:
        raise HTTPException(
            409, detail=f"Stage {stage_id} blocked by unapproved gate G2"
        )


def _crash(pid: str, stage_id: str, force: bool, quality: str | None) -> dict[str, Any]:
    raise RuntimeError("veo backend exploded")


@pytest.mark.parametrize(
    ("fake", "expected", "needle"),
    [
        (_gate_blocked, "paused", "unapproved gate G2"),
        (_crash, "failed", "veo backend exploded"),
    ],
)
def test_outcome_distinguishes_graceful_stop_from_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake: Callable[..., dict[str, Any]],
    expected: str,
    needle: str,
) -> None:
    monkeypatch.setattr(entrypoints, "run_project_stage", fake)
    pid = create_production(client)
    assert client.post(f"{BASE}/{pid}/stages/S4_SHOTS/run").status_code == 202
    last = wait_until_idle(client, pid)
    assert last["last_run"]["status"] == expected
    assert needle in last["last_run"]["error"] and needle in last["last_error"]


def _dead_run(pid: str, silent: timedelta) -> StageJob:
    then = utc_now() - silent
    job = StageJob(
        id=f"run_dead_{int(silent.total_seconds())}",
        created_by=Role.HUMAN,
        kind="stage",
        label="Resume keyframes",
        stage="S8_RENDER",
        run_status="running",
        started_at=then,
        heartbeat_at=then,
    )
    StageJobRepo(get_graph_store(pid)).claim(job, lambda _j: False)
    return job


def test_stale_heartbeat_reports_interrupted_and_resume_takes_over(
    client: TestClient, stage: BlockingStage
) -> None:
    pid = create_production(client)
    dead = _dead_run(pid, timedelta(minutes=10))  # the instance died mid-run
    st = status(client, pid)
    assert st["active_run"] is None and st["last_run"]["status"] == "interrupted"
    assert (
        "Resume" in st["last_run"]["error"]
        and st["last_error"] == st["last_run"]["error"]
    )
    stage.release.set()
    assert _resume(client, pid).status_code == 202  # not blocked by the dead run
    wait_until_idle(client, pid)
    stored = StageJobRepo(get_graph_store(pid)).get(dead.id)
    assert stored is not None and stored.run_status == "interrupted"


def test_recent_heartbeat_still_blocks(
    client: TestClient, stage: BlockingStage
) -> None:
    pid = create_production(client)
    _dead_run(pid, timedelta(seconds=20))  # silent, but within the stale window
    assert status(client, pid)["active_run"]["status"] == "running"
    assert _resume(client, pid).status_code == 409
    assert stage.calls == []


def _fingerprint(pid: str) -> tuple[list[str], dict[str, str]]:
    repo = get_repo(pid)
    runs = sorted(r.id for r in repo.list_generation_runs())
    sets = {
        sid: ks.id for sid, ks in KeyframeSetRepo(repo.store).active_by_shot().items()
    }
    return runs, sets


def test_non_forced_resume_after_completion_regenerates_nothing(
    client: TestClient,
) -> None:
    pid = create_production(client)
    assert (
        client.post(f"{BASE}/{pid}/run", json={"auto_approve_gates": True}).status_code
        == 202
    )
    done = wait_until_idle(client, pid, timeout_s=120)
    assert done["last_run"]["status"] == "completed", done
    before = _fingerprint(pid)
    assert before[0], "the full run rendered shots"
    assert _resume(client, pid).status_code == 202
    again = wait_until_idle(client, pid, timeout_s=120)
    assert again["last_run"]["status"] == "completed", again
    assert again["last_run"]["stages"] == [
        "S8_KEYFRAMES",
        "S8_RENDER",
        "S9_QA",
        "S10_ASSEMBLE",
    ]
    assert _fingerprint(pid) == before  # no new renders, no superseded keyframe sets

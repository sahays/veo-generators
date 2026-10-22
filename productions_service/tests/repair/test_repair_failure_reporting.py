"""Repair failures always close the S8_REPAIR StageRun with a readable error (type + message + shot).

Regression: `_tracked` only caught KeyError/StoryGraphError, so any other crash (provider
timeouts, RuntimeErrors from adapters) left the start record open forever with no error, and
an exception with an empty message was recorded as error="" with a non-FAILED status.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from conftest import seed_valid_graph
from fastapi import HTTPException
from services.repair_service import REPAIR_STAGE, _tracked
from storygraph.adapters.mock import MockVideoGenerator, MockVLMProvider
from storygraph.config import Config
from storygraph.errors import BudgetExceeded, ShotRepairError
from storygraph.repair import RepairReport
from storygraph.repair.loop import regenerate_shot
from storygraph.repo import Repo
from storygraph.schema import Status


class _CrashingVideo(MockVideoGenerator):
    def generate(self, package: Any) -> bytes:
        raise RuntimeError("veo quota exhausted")


def _run_tracked(repo: Repo, run: Any) -> HTTPException:
    pipe = cast(Any, SimpleNamespace(repo=repo))
    with pytest.raises(HTTPException) as info:
        _tracked(pipe, "repair:all_blocking", run)
    return info.value


def _last_run(repo: Repo) -> Any:
    runs = repo.list_stage_runs(REPAIR_STAGE)
    assert len(runs) == 2, "start + terminal record"
    return runs[-1]


def _raise(exc: BaseException) -> RepairReport:
    raise exc


def test_crash_with_empty_message_records_failed_run_with_type(tmp_repo: Repo) -> None:
    err = _run_tracked(tmp_repo, lambda: _raise(TimeoutError()))
    last = _last_run(tmp_repo)
    assert last.status == Status.FAILED and not last.completed
    assert last.error == "TimeoutError: (no message)"
    assert err.status_code == 500 and err.detail == last.error


def test_domain_error_stays_422_with_readable_error(tmp_repo: Repo) -> None:
    err = _run_tracked(tmp_repo, lambda: _raise(BudgetExceeded("render cap 40 hit")))
    assert err.status_code == 422
    assert _last_run(tmp_repo).error == "BudgetExceeded: render cap 40 hit"


def test_adapter_crash_names_the_shot_in_the_stage_run(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    video = _CrashingVideo(caps=default_cfg.video)
    with pytest.raises(ShotRepairError) as info:
        regenerate_shot(tmp_repo, default_cfg, video, MockVLMProvider(), "shot_1")
    assert info.value.shot_id == "shot_1"

    err = _run_tracked(
        tmp_repo,
        lambda: regenerate_shot(
            tmp_repo, default_cfg, video, MockVLMProvider(), "shot_1"
        ),
    )
    last = _last_run(tmp_repo)
    assert last.error == "shot shot_1: RuntimeError: veo quota exhausted"
    assert last.status == Status.FAILED and err.status_code == 500

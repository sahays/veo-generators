"""Regression tests for the S10 assembly gate (production p-zyt0jprz stitched failed shots)."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from conftest import seed_valid_graph
from storygraph.assembly import (
    PARTIAL_NOTE_PREFIX,
    assemble,
    evaluate_shot_readiness,
)
from storygraph.assembly import stitch as stitch_mod
from storygraph.config import Config
from storygraph.errors import ShotsNotApproved, StoryGraphError
from storygraph.pipeline import Pipeline, Stage, approve_gate, assemble_stage
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, ProjectMeta, QAReport, Role, Status

# Inserted out of story order on purpose: assembly must sort by story_order.
_SHOT_ORDER: dict[str, int] = {"shot_c": 30, "shot_a": 10, "shot_b": 20}


class _RecordingStitcher:
    def __init__(self) -> None:
        self.calls: list[list[bytes]] = []

    def __call__(self, clips: list[bytes]) -> bytes:
        self.calls.append(clips)
        return b"STITCHED:" + b"|".join(clips)


def _seed_shots(repo: Repo) -> None:
    base = seed_valid_graph(repo)
    repo.put_project_meta(ProjectMeta(id="test_proj", name="Gate", status="running"))
    for shot_id, order in _SHOT_ORDER.items():
        repo.put_shot(base.model_copy(update={"id": shot_id, "story_order": order}))
    repo.store.delete("shots", "shot_1")


def _add_run(
    repo: Repo, shot_id: str, attempt: int, status: Status, qa: QAReport | None = None
) -> None:
    uri = repo.blobs.put_bytes(
        f"clips/{shot_id}_{attempt}.mp4", f"{shot_id}#{attempt}".encode(), "video/mp4"
    )
    repo.add_generation_run(
        GenerationRun(
            id=f"run_{shot_id}_{attempt}",
            created_by=Role.PIPELINE,
            status=status,
            shot_id=shot_id,
            attempt=attempt,
            provider="mock",
            model="mock",
            compiled_prompt="p",
            seed=1,
            package_hash="h",
            output_video_uri=uri,
            qa_scores=qa,
        )
    )


def _physics_failure() -> QAReport:
    """A failed QA verdict WITHOUT style_drift/frozen_frame flags (the leaked path)."""
    return QAReport(
        passed=False,
        physics_plausibility=0.1,
        failure_reasons=["physics: cup floats mid-air"],
        artifact_flags=["teleportation"],
    )


def test_strict_mode_raises_with_exact_blocking_ids(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    _add_run(tmp_repo, "shot_a", 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 1, Status.FAILED, _physics_failure())
    stitcher = _RecordingStitcher()
    with pytest.raises(ShotsNotApproved) as exc:
        assemble(tmp_repo, stitcher=stitcher)
    assert list(exc.value.blocking) == ["shot_b", "shot_c"]
    assert "physics: cup floats mid-air" in exc.value.blocking["shot_b"]
    assert stitcher.calls == []
    meta = tmp_repo.get_project_meta()
    assert meta is not None and meta.final_video_uri is None


def test_failed_run_without_style_drift_is_never_picked(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    for shot_id in ("shot_a", "shot_c"):
        _add_run(tmp_repo, shot_id, 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 1, Status.FAILED, _physics_failure())
    readiness = evaluate_shot_readiness(tmp_repo)
    assert [r.shot_id for r in readiness.ready_shots] == ["shot_a", "shot_c"]
    blocking = readiness.blocking[0]
    assert (blocking.shot_id, blocking.latest_status) == ("shot_b", "failed")
    assert blocking.artifact_flags == ["teleportation"]
    assert readiness.is_complete is False


def test_latest_approved_run_wins_even_after_later_failure(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    for shot_id in _SHOT_ORDER:
        _add_run(tmp_repo, shot_id, 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 2, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 3, Status.FAILED, _physics_failure())
    readiness = evaluate_shot_readiness(tmp_repo)
    winner = {r.shot_id: r.run_id for r in readiness.ready_shots}["shot_b"]
    assert winner == "run_shot_b_2" and readiness.is_complete


def test_all_approved_stitches_in_story_order(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    for shot_id in _SHOT_ORDER:
        _add_run(tmp_repo, shot_id, 1, Status.APPROVED)
    stitcher = _RecordingStitcher()
    final_uri = assemble(tmp_repo, stitcher=stitcher)
    assert stitcher.calls == [[b"shot_a#1", b"shot_b#1", b"shot_c#1"]]
    assert tmp_repo.blobs.get_bytes(final_uri).startswith(b"STITCHED:shot_a#1")
    meta = tmp_repo.get_project_meta()
    assert meta is not None
    assert (meta.status, meta.error_message) == ("completed", None)


def test_partial_mode_skips_blocking_and_records_them(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    _add_run(tmp_repo, "shot_c", 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 1, Status.FAILED, _physics_failure())
    _add_run(tmp_repo, "shot_a", 1, Status.APPROVED)
    stitcher = _RecordingStitcher()
    assemble(tmp_repo, allow_partial=True, stitcher=stitcher)
    assert stitcher.calls == [[b"shot_a#1", b"shot_c#1"]]
    meta = tmp_repo.get_project_meta()
    assert meta is not None and meta.status == "completed_partial"
    assert meta.error_message == PARTIAL_NOTE_PREFIX + "shot_b"
    assert meta.skipped_shot_ids == ["shot_b"]


def test_partial_mode_with_zero_approved_raises(tmp_repo: Repo) -> None:
    _seed_shots(tmp_repo)
    _add_run(tmp_repo, "shot_a", 1, Status.FAILED, _physics_failure())
    stitcher = _RecordingStitcher()
    with pytest.raises(ShotsNotApproved) as exc:
        assemble(tmp_repo, allow_partial=True, stitcher=stitcher)
    assert set(exc.value.blocking) == set(_SHOT_ORDER)
    assert stitcher.calls == []


def test_ffmpeg_failure_raises_instead_of_fake_mp4(
    tmp_repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_shots(tmp_repo)
    for shot_id in _SHOT_ORDER:
        _add_run(tmp_repo, shot_id, 1, Status.APPROVED)

    def _failing_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            cmd, 1, b"", b"Invalid data found when processing input"
        )

    monkeypatch.setattr(stitch_mod.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(stitch_mod.subprocess, "run", _failing_run)
    with pytest.raises(StoryGraphError, match="Invalid data found"):
        assemble(tmp_repo)
    meta = tmp_repo.get_project_meta()
    assert meta is not None and meta.final_video_uri is None


def test_pipeline_s10_gate_sets_needs_review_then_partial_completes(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    stitcher = _RecordingStitcher()
    monkeypatch.setattr(assemble_stage, "select_stitcher", lambda _provider: stitcher)
    _seed_shots(tmp_repo)
    _add_run(tmp_repo, "shot_a", 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_b", 1, Status.APPROVED)
    _add_run(tmp_repo, "shot_c", 1, Status.FAILED, _physics_failure())
    for gate_id in ("G1", "G2", "G3"):
        approve_gate(tmp_repo, gate_id)  # type: ignore[arg-type]
    pipe = Pipeline(repo=tmp_repo, cfg=default_cfg)
    with pytest.raises(ShotsNotApproved):
        pipe.run_stage(Stage.S10_ASSEMBLE, force=True)
    meta = tmp_repo.get_project_meta()
    assert meta is not None and meta.status == "needs_review"
    assert meta.error_message is not None and "shot_c" in meta.error_message
    assert stitcher.calls == []
    pipe.assemble_approved_only()
    assert stitcher.calls == [[b"shot_a#1", b"shot_b#1"]]
    done = tmp_repo.get_project_meta()
    assert done is not None and done.status == "completed_partial"
    assert done.error_message == PARTIAL_NOTE_PREFIX + "shot_c"


def test_regression_resolved_crs_with_empty_flags_still_gate_strict(
    tmp_repo: Repo, default_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """failed runs with empty flags + resolved CRs => strict assemble raises ShotsNotApproved."""
    stitcher = _RecordingStitcher()
    monkeypatch.setattr(assemble_stage, "select_stitcher", lambda _provider: stitcher)
    _seed_shots(tmp_repo)
    _add_run(tmp_repo, "shot_a", 1, Status.APPROVED)
    qa = QAReport(passed=False, failure_reasons=["blurry"], artifact_flags=[])
    _add_run(tmp_repo, "shot_b", 1, Status.FAILED, qa)
    _add_run(tmp_repo, "shot_c", 1, Status.APPROVED)

    from storygraph.schema import ChangeRequest, Role

    cr = ChangeRequest(
        id="cr_1",
        created_by=Role.CRITIC,
        from_role=Role.CRITIC,
        to_role=Role.DIRECTOR,
        target_node_id="shot_b",
        reason="blurry",
    )
    tmp_repo.add_change_request(cr)
    tmp_repo.resolve_change_request(cr.id, "accepted")
    assert tmp_repo.list_change_requests(open_only=True) == []
    for gate_id in ("G1", "G2", "G3"):
        approve_gate(tmp_repo, gate_id)  # type: ignore[arg-type]

    pipe = Pipeline(repo=tmp_repo, cfg=default_cfg)
    with pytest.raises(ShotsNotApproved) as exc:
        pipe.run_stage(Stage.S10_ASSEMBLE, force=True)

    assert "shot_b" in exc.value.blocking
    assert stitcher.calls == []
    meta = tmp_repo.get_project_meta()
    assert meta is not None and meta.status == "needs_review"

"""Previz service: generic-stage retry reuses the last request, conflicts, signed URLs only."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import services.previz_service as svc
from conftest import seed_valid_graph
from storygraph.repo import Repo
from storygraph.repo.previz_shots import PrevizRunRepo
from storygraph.schema import Role
from storygraph.schemas.previz import PrevizRun, PrevizShot, PrevizVariantRecord


STARTED: list[PrevizRun] = []


@pytest.fixture
def wired(tmp_repo: Repo, monkeypatch: pytest.MonkeyPatch) -> Repo:
    seed_valid_graph(tmp_repo)
    monkeypatch.setattr(svc, "_repo", lambda project_id: tmp_repo)
    monkeypatch.setattr(svc, "_spawn", lambda project_id, run: STARTED.append(run))
    STARTED.clear()
    return tmp_repo


def _past_run(repo: Repo, status: str, started: str) -> None:
    PrevizRunRepo(repo.store).put(
        PrevizRun(id="pzr_old", created_by=Role.HUMAN, variant="both", scene_ids=["scn_1"],
                  force=True, run_status=status, started_at=started)  # type: ignore[arg-type]
    )  # fmt: skip


def test_generic_retry_repeats_last_request_without_force(wired: Repo) -> None:
    _past_run(wired, "failed", "2026-10-23T00:00:00+00:00")
    out = svc.retry_last_previz("p")
    run = PrevizRunRepo(wired.store).get(out["stage_run_id"])
    assert out["accepted"] is True and run is not None
    assert (run.variant, run.scene_ids, run.force) == ("both", ["scn_1"], False)
    assert [r.id for r in STARTED] == [run.id]


def test_generic_retry_defaults_to_previz_only(wired: Repo) -> None:
    out = svc.retry_last_previz("p")
    run = PrevizRunRepo(wired.store).get(out["stage_run_id"])
    assert run is not None and (run.variant, run.scene_ids) == ("previz_only", None)


def test_live_run_conflicts_but_stale_running_record_does_not(wired: Repo) -> None:
    from datetime import UTC, datetime

    _past_run(wired, "running", datetime.now(UTC).isoformat())
    with pytest.raises(HTTPException) as exc:
        svc.retry_last_previz("p")
    assert exc.value.status_code == 409
    _past_run(wired, "running", "2020-01-01T00:00:00+00:00")  # died with its instance
    assert svc.retry_last_previz("p")["accepted"] is True


def test_unknown_scene_rejected(wired: Repo) -> None:
    body = svc.PrevizRunPayload(variant="previz_only", scene_ids=["scn_nope"])
    with pytest.raises(HTTPException) as exc:
        svc.start_previz_run("p", body)
    assert exc.value.status_code == 404


def test_only_existing_media_get_urls(wired: Repo) -> None:
    present = wired.blobs.put_bytes("previz/s/a.mp4", b"mp4", "video/mp4")
    frame = wired.blobs.put_bytes("previz/s/f0.png", b"png", "image/png")
    missing = present.replace("a.mp4", "gone.mp4")
    ps = PrevizShot(
        id="pzs_s_1", created_by=Role.PIPELINE, shot_id="shot_1", scene_id="scn_1",
        clip_index=1, previz_status="done", previz_video_uri=present,
        variants=[PrevizVariantRecord(variant="E2_keyframe_restyle", status="done",
                                      video_uri=missing, frame_uris=[frame, missing])],
    )  # fmt: skip
    shot = wired.get_shot("shot_1")
    assert shot is not None
    view = svc._shot_view(shot, ps, svc._signed(wired, svc._record_uris([ps], [])))
    assert view.previz_video_url == present
    assert view.variants[0].video_url is None and view.variants[0].frame_urls == [frame]

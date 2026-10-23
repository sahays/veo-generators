"""Lean snapshot shaping: active run per shot, no prompt bodies, sign only returned URIs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pytest
from conftest import seed_valid_graph
from services.snapshot import format_graph_snapshot
from services.snapshot.shaping import select_active_runs
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import Asset, GenerationRun, ProjectMeta, QAReport, Role, Status
from storygraph.schemas.generation import PromptVersion
from storygraph.store import LocalBlobStore, MemoryStore
from storygraph.store.codec import encode

SPEC_SENTINEL = "SPEC-BODY-MUST-NOT-LEAK"


class RecordingBlobs(LocalBlobStore):
    """Signs as `signed:<uri>` and records every URI it was asked to sign."""

    def __init__(self, root: Path) -> None:
        super().__init__(root_dir=root, project_id="test_proj")
        self.signed: list[str] = []

    def sign_url(self, uri: str) -> str:
        self.signed.append(uri)
        return f"signed:{uri}"

    def sign_urls(self, uris: Iterable[str]) -> dict[str, str]:
        return {u: self.sign_url(u) for u in {u for u in uris if u}}


def _run(
    run_id: str, attempt: int, status: Status, qa: QAReport | None, **kw: object
) -> GenerationRun:
    return GenerationRun(
        id=run_id, created_by=Role.PIPELINE, status=status, shot_id="shot_1",
        attempt=attempt, provider="mock", model="m", compiled_prompt=f"prompt {run_id}",
        seed=attempt, package_hash="h", output_video_uri=f"gs://b/{run_id}.mp4",
        qa_scores=qa, spec_json=SPEC_SENTINEL, **kw,  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.fixture()
def seeded(tmp_path: Path) -> tuple[Repo, RecordingBlobs]:
    blobs = RecordingBlobs(tmp_path / "blobs")
    repo = Repo(store=MemoryStore(project_id="test_proj"), blobs=blobs)
    seed_valid_graph(repo)
    repo.put_project_meta(ProjectMeta(id="test_proj", name="T", base_concept="c"))
    ids: dict[str, str] = {}
    for aid in ("ast_ff_used", "ast_ff_orphan"):
        ids[aid] = repo.add_asset(Asset(
            id=aid, created_by=Role.PIPELINE, kind="first_frame",
            uri=f"gs://b/{aid}.png", sha256=aid, generation_prompt="p", model="m",
        )).id  # fmt: skip
    bad = QAReport(
        passed=False, artifact_flags=["frozen_frame"], physics_plausibility=0.1
    )
    repo.add_generation_run(_run("run_1", 1, Status.APPROVED, QAReport()))
    repo.add_generation_run(
        _run(
            "run_2", 2, Status.RENDERED, bad, first_frame_asset_id=ids["ast_ff_orphan"]
        )
    )
    repo.add_generation_run(_run("run_3", 3, Status.APPROVED, QAReport(),
                                 first_frame_asset_id=ids["ast_ff_used"]))  # fmt: skip
    pv = PromptVersion(id="pv_1", created_by=Role.PIPELINE, shot_id="shot_1",
                       spec_json=SPEC_SENTINEL, spec_hash="x", status="active")  # fmt: skip
    repo.store.set("prompt_versions", pv.id, encode(pv))
    return repo, blobs


def test_rank_beats_recency_and_ties_go_to_later_attempt() -> None:
    good = _run("r1", 1, Status.APPROVED, QAReport())
    newer_bad = _run("r2", 2, Status.RENDERED, QAReport(passed=False))
    newer_equal = _run("r3", 3, Status.APPROVED, QAReport())
    assert select_active_runs([good, newer_bad])["shot_1"].id == "r1"
    assert select_active_runs([good, newer_bad, newer_equal])["shot_1"].id == "r3"


def test_snapshot_returns_one_slim_run_per_shot_with_history_counts(
    seeded: tuple[Repo, RecordingBlobs], default_cfg: Config
) -> None:
    repo, _ = seeded
    sg = format_graph_snapshot(repo, default_cfg)["story_graph"]
    assert [r["id"] for r in sg["generation_runs"]] == ["run_3"]
    assert sg["generation_run_counts"] == {"shot_1": 3}
    assert sg["generation_runs_total"] == 3
    run = sg["generation_runs"][0]
    assert "compiled_prompt" not in run and "spec_json" not in run
    assert run["output_video_signed_url"] == "signed:gs://b/run_3.mp4"
    shot = next(s for s in sg["shots"] if s["id"] == "shot_1")
    assert shot["latest_run_id"] == "run_3" and "latest_run" not in shot
    assert shot["active_prompt_version"]["id"] == "pv_1"


def test_snapshot_never_ships_prompt_bodies_or_scene_steps(
    seeded: tuple[Repo, RecordingBlobs], default_cfg: Config
) -> None:
    repo, _ = seeded
    snap = format_graph_snapshot(repo, default_cfg)
    assert SPEC_SENTINEL not in json.dumps(snap)
    scene = snap["story_graph"]["scenes"][0]
    assert "interaction_steps" not in scene and scene["interaction_step_count"] == 1


def test_only_returned_assets_are_signed(
    seeded: tuple[Repo, RecordingBlobs], default_cfg: Config
) -> None:
    repo, blobs = seeded
    sg = format_graph_snapshot(repo, default_cfg)["story_graph"]
    assert (
        "gs://b/ast_ff_orphan.png" not in blobs.signed
    )  # only a losing attempt used it
    assert (
        "gs://b/run_1.mp4" not in blobs.signed
        and "gs://b/run_2.mp4" not in blobs.signed
    )
    returned = {a["uri"]: a for a in sg["assets"]}
    assert (
        returned["gs://b/ast_ff_used.png"]["signed_url"]
        == "signed:gs://b/ast_ff_used.png"
    )
    assert "generation_prompt" not in returned["gs://b/ast_ff_used.png"]
    embedded = {a["id"] for app in sg["appearances"] for a in app["assets"]}
    assert embedded.isdisjoint(
        {a["id"] for a in sg["assets"]}
    )  # appearance assets are not duplicated
    assert len(blobs.signed) == len(set(blobs.signed))  # each URI signed once

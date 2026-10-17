"""Milestone 6: End-to-End Pipeline S0..S10, Gates, Retries, Budget Caps & FastAPI Service tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from main import app
from storygraph.adapters.mock import (
    MockImageGenerator,
    MockVideoGenerator,
    MockVLMProvider,
)
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.errors import BudgetExceeded, GateBlocked
from storygraph.pipeline import Pipeline, Stage, approve_gate
from storygraph.repo import Repo
from storygraph.schema import EntityType, ProjectMeta, Status
from storygraph.views import entity_design_view, shot_view

_SAMPLE_STORY = (
    "Detective Arjun enters the rain-lit corner cafe in a trenchcoat carrying a brass compass. "
    "He meets Dr. Meera at the table. Later, Arjun steps onto the monsoon skyline rooftop in a formal suit."
)


def _advance_pipeline_through_gates(pipe: Pipeline, tmp_repo: Repo) -> None:
    with pytest.raises(GateBlocked) as exc_g1:
        pipe.run_until_gate_or_done(story_text=_SAMPLE_STORY, auto_approve_gates=False)
    assert exc_g1.value.gate_id == "G1"
    approve_gate(tmp_repo, "G1")
    with pytest.raises(GateBlocked) as exc_g2:
        pipe.run_until_gate_or_done()
    assert exc_g2.value.gate_id == "G2"
    approve_gate(tmp_repo, "G2")
    with pytest.raises(GateBlocked) as exc_g3:
        pipe.run_until_gate_or_done()
    assert exc_g3.value.gate_id == "G3"


def test_end_to_end_pipeline_gates_retries_and_idempotency(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    vlm = MockVLMProvider(fail_shots_once={"shot_scn_001_01"})
    video_gen = MockVideoGenerator(caps=default_cfg.video)
    pipe = Pipeline(
        repo=tmp_repo,
        cfg=default_cfg,
        image_gen=MockImageGenerator(),
        video_gen=video_gen,
        vlm=vlm,
    )
    _advance_pipeline_through_gates(pipe, tmp_repo)
    assert len(tmp_repo.list_entities(EntityType.CHARACTER)) >= 2
    assert len(tmp_repo.list_appearances()) >= 4 and len(tmp_repo.list_shots()) >= 4

    approve_gate(tmp_repo, "G3")
    completed_runs = pipe.run_until_gate_or_done()
    assert any(
        sr.stage == str(Stage.S10_ASSEMBLE) and sr.completed for sr in completed_runs
    )
    s1_runs = tmp_repo.list_generation_runs(shot_id="shot_scn_001_01")
    assert (
        len(s1_runs) == 2
        and s1_runs[0].status == Status.FAILED
        and s1_runs[1].status == Status.APPROVED
    )

    calls_before = len(video_gen.calls)
    pipe.run_stage(Stage.S8_RENDER, force=True)
    assert len(video_gen.calls) == calls_before


def test_budget_exceeded_cap(tmp_repo: Repo, default_cfg: Config) -> None:
    default_cfg.caps.stage_token_cap = 10
    pipe = Pipeline(repo=tmp_repo, cfg=default_cfg)
    with pytest.raises(BudgetExceeded):
        pipe.run_until_gate_or_done(
            story_text="Arjun walks into the rain-lit cafe with a brass compass.",
            auto_approve_gates=True,
        )


def _create_and_advance_to_g3(
    client: TestClient,
) -> tuple[str, list[dict[str, object]]]:
    payload = {
        "name": "Monsoon Protocol",
        "type": "movie",
        "base_concept": "Detective Arjun meets Dr. Meera at a rain-lit cafe with a brass compass.",
        "video_length": "16",
        "orientation": "16:9",
        "language": "en-IN",
        "auto_approve_gates": False,
    }
    res_create = client.post("/api/v1/productions", json=payload)
    assert res_create.status_code == 200
    pid = str(res_create.json()["id"])
    snap1 = client.post(f"/api/v1/productions/{pid}/run").json()
    assert snap1["blocked_gate"] == "G1"
    snap2 = client.post(f"/api/v1/productions/{pid}/gates/G1/approve").json()
    assert snap2["blocked_gate"] == "G2"
    snap3 = client.post(f"/api/v1/productions/{pid}/gates/G2/approve").json()
    assert snap3["blocked_gate"] == "G3"
    return pid, snap3["story_graph"]["shots"]


def test_fastapi_productions_service_endpoints() -> None:
    client = TestClient(app)
    res_health = client.get("/health")
    assert (
        res_health.status_code == 200
        and res_health.json()["service"] == "veo-generators-productions"
    )
    pid, shots = _create_and_advance_to_g3(client)
    assert len(shots) >= 2
    first_shot_id = str(shots[0]["id"])
    res_compile = client.post(
        f"/api/v1/productions/{pid}/shots/{first_shot_id}/compile"
    )
    assert res_compile.status_code == 200
    compiled = res_compile.json()
    assert "STYLE:" in compiled["compiled_prompt"] and compiled["package_hash"]
    res_g3 = client.post(f"/api/v1/productions/{pid}/gates/G3/approve")
    assert res_g3.status_code == 200
    snap_done = res_g3.json()
    assert snap_done["status"] == "completed" and snap_done["final_video_url"]


def test_epic_name_normalization_hindi_dialogue_and_deduplication(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    story = (
        "Visual style: Chibi with dreamy, cotton-candy, and pastel colors\n\n"
        "Rama, Sita, and Lakshmana enter the forest of Panchavati. "
        "Surpanakha confronts them, and Ravana abducts Sita with the Golden Deer while Jatayu tries to save her."
    )
    tmp_repo.put_project_meta(
        ProjectMeta(
            id="p_aranya",
            name="Aranya Kand",
            base_concept=story,
            story_text=story,
            language="hi-IN",
            auto_approve_gates=True,
        )
    )
    pipe = Pipeline(
        repo=tmp_repo,
        cfg=default_cfg,
        image_gen=MockImageGenerator(),
        video_gen=MockVideoGenerator(caps=default_cfg.video),
        vlm=MockVLMProvider(),
    )
    pipe.run_until_gate_or_done(story_text=story, auto_approve_gates=True)

    chars = {
        c.id: c.canonical_name for c in tmp_repo.list_entities(EntityType.CHARACTER)
    }
    assert "char_ram" in chars and "Rama" not in chars["char_ram"]
    assert "char_lakshman" in chars and "Lakshmana" not in chars["char_lakshman"]
    assert "char_ravan" in chars and "Ravana" not in chars["char_ravan"]
    assert "char_shurpanakha" in chars and "Surpanakha" not in chars["char_shurpanakha"]
    assert "char_jatayu" in chars
    assert entity_design_view(tmp_repo, "char_jatayu").required_state_labels == [
        "default"
    ]
    assert all(d.language == "hi-IN" for d in tmp_repo.list_dialogue())
    sv = shot_view(tmp_repo, "shot_scn_001_01")
    pkg = compile_shot(
        sv,
        select_references(sv, default_cfg, repo=tmp_repo),
        default_cfg,
        project_id="p_aranya",
    )
    assert "Hindi (hi-IN)" in pkg.compiled_prompt

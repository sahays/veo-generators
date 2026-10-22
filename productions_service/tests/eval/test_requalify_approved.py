"""S9 re-qualification of stale-gate APPROVED clips (live critic re-score, no re-render).

p-0irbygdv: clips approved before the wardrobe / key-prop rules kept their approval. After a
gate-rules change, S9 must re-score them; a clip that now blocks flips to FAILED so the
shot is blocking again and the repair loop picks it up.
"""

from __future__ import annotations

from typing import Any

from conftest import seed_valid_graph
from pydantic import BaseModel
from storygraph.adapters.mock import MockVideoGenerator, MockVLMProvider
from storygraph.assembly import evaluate_shot_readiness
from storygraph.config import Config
from storygraph.eval.rubric import WardrobeCheck
from storygraph.pipeline.requalify import evaluate_missing_qa
from storygraph.qa.critic.rubric import read_rubric_keys
from storygraph.repair.loop import regenerate_shot
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, Status


def _outfit_swap(_images: list[bytes], prompt: str, schema: type[BaseModel]) -> Any:
    """Live-like critic: every subject's outfit changes mid-clip (new wardrobe check)."""
    rubric = schema.mock_response(prompt)  # type: ignore[attr-defined]
    checks = [
        WardrobeCheck(
            subject=s,
            garments_seen="t=0s blue dress; t=3s green jacket",
            matches_reference=False,
            changed_between_frames=True,
            timestamps_s=[3.0],
            evidence="dress becomes a green jacket at t=3.0s",
        )
        for s in read_rubric_keys(prompt).get("subjects", [])
    ]
    return rubric.model_copy(update={"wardrobe_checks": checks})


def _approved_run(repo: Repo, cfg: Config) -> GenerationRun:
    regenerate_shot(
        repo, cfg, MockVideoGenerator(caps=cfg.video), MockVLMProvider(), "shot_1"
    )
    (run,) = [
        r
        for r in repo.list_generation_runs(shot_id="shot_1")
        if r.status == Status.APPROVED
    ]
    assert evaluate_shot_readiness(repo).is_complete
    return run


def _age_gate(repo: Repo, run: GenerationRun) -> None:
    assert run.qa_scores is not None
    old = run.qa_scores.model_copy(update={"gate_version": "pre-wardrobe-gate"})
    repo.update_generation_run_qa(run.id, qa_scores=old, status=Status.APPROVED)


def _status(repo: Repo, run_id: str) -> Status:
    (run,) = [r for r in repo.list_generation_runs(shot_id="shot_1") if r.id == run_id]
    return run.status


def test_stale_approval_with_outfit_change_is_revoked_and_shot_blocks(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    run = _approved_run(tmp_repo, default_cfg)
    _age_gate(tmp_repo, run)
    vlm = MockVLMProvider(custom_responder=_outfit_swap)

    assert evaluate_missing_qa(tmp_repo, default_cfg, vlm) == 1
    assert _status(tmp_repo, run.id) == Status.FAILED
    blocking = evaluate_shot_readiness(tmp_repo).blocking
    assert [b.shot_id for b in blocking] == ["shot_1"]
    (latest,) = [
        r for r in tmp_repo.list_generation_runs(shot_id="shot_1") if r.id == run.id
    ]
    assert latest.qa_scores is not None
    assert any(d.type == "wardrobe_change" for d in latest.qa_scores.defects)


def test_approval_under_current_gate_is_not_rescored(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    run = _approved_run(tmp_repo, default_cfg)
    vlm = MockVLMProvider(custom_responder=_outfit_swap)

    assert evaluate_missing_qa(tmp_repo, default_cfg, vlm) == 0
    assert vlm.calls == [] and _status(tmp_repo, run.id) == Status.APPROVED


def test_stale_approval_that_still_passes_keeps_approval_with_new_gate(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    seed_valid_graph(tmp_repo)
    run = _approved_run(tmp_repo, default_cfg)
    _age_gate(tmp_repo, run)

    assert evaluate_missing_qa(tmp_repo, default_cfg, MockVLMProvider()) == 0
    (fresh,) = [
        r for r in tmp_repo.list_generation_runs(shot_id="shot_1") if r.id == run.id
    ]
    assert fresh.status == Status.APPROVED
    assert (
        fresh.qa_scores is not None
        and fresh.qa_scores.gate_version != "pre-wardrobe-gate"
    )

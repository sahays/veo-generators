"""QA -> graph feedback: Critic ChangeRequests close when their shot is fixed."""

from __future__ import annotations

from conftest import seed_valid_graph
from storygraph.repo import Repo
from storygraph.schema import ChangeRequest, GenerationRun, QAReport, Role, Status


def _cr(repo: Repo, cr_id: str, from_role: Role = Role.CRITIC) -> None:
    repo.add_change_request(
        ChangeRequest(
            id=cr_id,
            created_by=from_role,
            status=Status.PROPOSED,
            from_role=from_role,
            to_role=Role.DIRECTOR,
            target_node_id="shot_1",
            reason="failed QA after repairs",
        )
    )


def _run(repo: Repo, attempt: int) -> str:
    run = GenerationRun(
        id=f"run_{attempt}",
        created_by=Role.PIPELINE,
        shot_id="shot_1",
        attempt=attempt,
        provider="mock",
        model="mock",
        compiled_prompt="p",
        seed=1,
        package_hash="h",
    )
    return repo.add_generation_run(run).id


def _resolution(repo: Repo, cr_id: str) -> tuple[str, Status]:
    cr = next(c for c in repo.list_change_requests(open_only=False) if c.id == cr_id)
    return cr.resolution, cr.status


def test_critic_cr_closes_on_approved_run_but_not_on_failed_qa(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    run_id = _run(tmp_repo, 1)
    _cr(tmp_repo, "cr_critic")
    _cr(tmp_repo, "cr_writer", from_role=Role.SCREENWRITER)
    tmp_repo.update_generation_run_qa(run_id, QAReport(passed=False), Status.FAILED)
    assert _resolution(tmp_repo, "cr_critic")[0] == "open"
    tmp_repo.update_generation_run_qa(run_id, QAReport(passed=True), Status.APPROVED)
    assert _resolution(tmp_repo, "cr_critic") == ("accepted", Status.APPROVED)
    assert _resolution(tmp_repo, "cr_writer")[0] == "open"  # not a Critic finding


def test_critic_cr_closes_when_shot_is_rerendered(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    _run(tmp_repo, 1)
    _cr(tmp_repo, "cr_critic")
    _run(tmp_repo, 2)
    assert _resolution(tmp_repo, "cr_critic") == ("accepted", Status.SUPERSEDED)


def test_critic_cr_closes_only_when_shot_spec_changes(tmp_repo: Repo) -> None:
    shot = seed_valid_graph(tmp_repo)
    tmp_repo.put_shot(shot.model_copy(update={"content_hash": "h1"}))
    _cr(tmp_repo, "cr_critic")
    current = tmp_repo.get_shot(shot.id)
    assert current is not None
    tmp_repo.put_shot(current)  # same spec re-saved: CR stays open
    assert _resolution(tmp_repo, "cr_critic")[0] == "open"
    tmp_repo.put_shot(current.model_copy(update={"content_hash": "h2"}))
    assert _resolution(tmp_repo, "cr_critic") == ("accepted", Status.SUPERSEDED)

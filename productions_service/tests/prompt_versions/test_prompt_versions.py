"""Prompt versioning: dedupe, lineage, activation/rollback, render override, run linkage."""

from __future__ import annotations

import json

import pytest
from conftest import seed_valid_graph

from storygraph.adapters.mock import MockVideoGenerator, MockVLMProvider
from storygraph.config import Config
from storygraph.pipeline import shot_attempt
from storygraph.pipeline.prompt_versioning import summarize_report
from storygraph.pipeline.shot_attempt import RenderDeps, render_attempt
from storygraph.repo import Repo
from storygraph.repo.prompt_versions import PromptDraft, PromptVersionRepo
from storygraph.schema import DimensionScore, GenerationRun, QAReport, Shot, Status

_SPEC_A = '{"task":"render_video_clip","summary":"a","constraints":[]}'
_SPEC_B = '{"task":"render_video_clip","summary":"b","constraints":[]}'


def _versions(repo: Repo) -> PromptVersionRepo:
    return PromptVersionRepo(repo.store)


def test_identical_spec_dedupes_even_when_reformatted(tmp_repo: Repo) -> None:
    pvs = _versions(tmp_repo)
    first = pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_A))
    pretty = json.dumps(json.loads(_SPEC_A), indent=2, sort_keys=False)
    again = pvs.create(PromptDraft(shot_id="s1", spec_json=pretty, author="human"))
    other_shot = pvs.create(PromptDraft(shot_id="s2", spec_json=_SPEC_A))
    assert again.id == first.id and again.author == "compiler"
    assert other_shot.id == "pv_s2_1"  # dedupe is per shot
    assert len(pvs.list_for_shot("s1")) == 1


def test_lineage_parent_and_patch(tmp_repo: Repo) -> None:
    pvs = _versions(tmp_repo)
    v1 = pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_A))
    v2 = pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_B, parent_id=v1.id))
    assert (v1.id, v2.id) == ("pv_s1_1", "pv_s1_2")
    assert v2.version == 2 and v2.parent_id == v1.id
    assert [(op.op, op.path, op.value) for op in v2.patch or []] == [
        ("replace", "/summary", "b")
    ]
    assert [pv.id for pv in pvs.list_for_shot("s1")] == [v1.id, v2.id]


def test_single_active_and_rollback(tmp_repo: Repo) -> None:
    pvs = _versions(tmp_repo)
    v1 = pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_A))
    v2 = pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_B, parent_id=v1.id))
    assert pvs.active_for_shot("s1").id == v2.id  # type: ignore[union-attr]
    assert pvs.require(v1.id).status == "superseded"
    pvs.set_status(v2.id, "rejected")
    pvs.rollback("s1", v1.id)
    statuses = {pv.id: pv.status for pv in pvs.list_for_shot("s1")}
    assert statuses == {v1.id: "active", v2.id: "rejected"}  # rejected is not clobbered
    # Re-creating a superseded spec re-activates it instead of minting a new version.
    assert pvs.create(PromptDraft(shot_id="s1", spec_json=_SPEC_B)).status == "active"
    assert pvs.require(v1.id).status == "superseded"
    with pytest.raises(Exception, match="does not belong"):
        pvs.rollback("other_shot", v1.id)


@pytest.fixture()
def qa_report(monkeypatch: pytest.MonkeyPatch) -> QAReport:
    report = QAReport(
        passed=True,
        eval_overall=0.82,
        dimension_scores=[
            DimensionScore(dimension="identity", score=0.9, confidence=1.0)
        ],
    )

    def _critic(
        repo: Repo, cfg: Config, vlm: object, shot: Shot, run: GenerationRun
    ) -> QAReport:
        repo.update_generation_run_qa(
            run_id=run.id, qa_scores=report, status=Status.APPROVED
        )
        return report

    monkeypatch.setattr(shot_attempt, "evaluate_clip_qa", _critic)
    return report


def _render(
    repo: Repo, cfg: Config, shot: Shot
) -> tuple[MockVideoGenerator, GenerationRun]:
    video = MockVideoGenerator(caps=cfg.video)
    render_attempt(RenderDeps(repo, cfg, video, MockVLMProvider()), shot, 1, False)
    return video, repo.list_generation_runs(shot_id=shot.id)[-1]


def _human_version(
    repo: Repo, shot: Shot, spec_json: str, content_hash: str | None
) -> str:
    active = _versions(repo).active_for_shot(shot.id)
    return (
        _versions(repo)
        .create(
            PromptDraft(
                shot_id=shot.id,
                spec_json=spec_json,
                author="human",
                parent_id=active.id if active else None,
                shot_content_hash=content_hash,
            )
        )
        .id
    )


def test_compiled_render_links_run_and_records_result(
    tmp_repo: Repo, default_cfg: Config, qa_report: QAReport
) -> None:
    shot = seed_valid_graph(tmp_repo)
    video, run = _render(tmp_repo, default_cfg, shot)
    pv = _versions(tmp_repo).require(run.prompt_version_id or "")
    assert pv.author == "compiler" and pv.spec_json == video.calls[-1].compiled_prompt
    assert pv.run_ids == [run.id] and pv.eval_score == pytest.approx(0.82)
    assert pv.eval_summary and pv.eval_summary["dimensions"] == {"identity": 0.9}


def test_render_uses_active_human_version(
    tmp_repo: Repo, default_cfg: Config, qa_report: QAReport
) -> None:
    shot = seed_valid_graph(tmp_repo)
    _, first = _render(tmp_repo, default_cfg, shot)
    edited = json.loads(first.compiled_prompt) | {"summary": "human-tuned summary"}
    current = tmp_repo.get_shot(shot.id) or shot
    human_id = _human_version(
        tmp_repo, current, json.dumps(edited), current.content_hash
    )
    video, run = _render(tmp_repo, default_cfg, current)
    assert (
        json.loads(video.calls[-1].compiled_prompt)["summary"] == "human-tuned summary"
    )
    assert run.prompt_version_id == human_id
    assert run.package_hash != first.package_hash
    assert _versions(tmp_repo).active_for_shot(shot.id).id == human_id  # type: ignore[union-attr]


def test_content_change_supersedes_human_version(
    tmp_repo: Repo, default_cfg: Config, qa_report: QAReport
) -> None:
    shot = seed_valid_graph(tmp_repo)
    human_id = _human_version(tmp_repo, shot, _SPEC_A, "stale-content-hash")
    video, run = _render(tmp_repo, default_cfg, shot)
    pv = _versions(tmp_repo).require(run.prompt_version_id or "")
    assert pv.author == "compiler" and pv.parent_id == human_id
    assert pv.reason == "shot content changed"
    assert video.calls[-1].compiled_prompt != _SPEC_A
    assert _versions(tmp_repo).require(human_id).status == "superseded"


def test_summary_tolerates_reports_without_eval_engine_fields() -> None:
    legacy = QAReport(action_achieved=0.4, physics_plausibility=0.6, passed=False)
    score, summary = summarize_report(legacy)
    assert score == pytest.approx((0.4 + 0.6 + 4 * 1.0) / 6)
    assert summary["dimensions"] == {} and summary["passed"] is False
    assert summarize_report(None) == (None, {})

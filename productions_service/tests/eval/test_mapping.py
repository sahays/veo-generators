"""S9 critic -> eval engine -> QAReport mapping keeps legacy fields and adds dimension scores."""

from __future__ import annotations

import json

from conftest import seed_valid_graph
from eval_clips import SPEC

from storygraph.adapters.mock import MockVLMProvider
from storygraph.agents.critic import evaluate_clip_qa
from storygraph.config import Config
from storygraph.eval.rubric import EvalRubric, ScriptVerdict
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, Role, Status

_KEYS = (
    'RUBRIC_KEYS={"steps":[1],"subjects":["Pip"],"objects":["Bowl"],'
    '"speakers":["Pip"],"continuity":false}'
)


def _run(repo: Repo, shot_id: str) -> GenerationRun:
    uri = repo.blobs.put_bytes("clips/e1.mp4", b"mp4", "video/mp4")
    return repo.add_generation_run(
        GenerationRun(
            id="run_e1",
            created_by=Role.PIPELINE,
            status=Status.RENDERED,
            shot_id=shot_id,
            attempt=1,
            provider="mock",
            model="mock",
            compiled_prompt=json.dumps(SPEC),
            seed=1,
            package_hash="h",
            output_video_uri=uri,
        )
    )


def _vlm(rubric: EvalRubric) -> MockVLMProvider:
    payload = rubric.model_dump_json()
    return MockVLMProvider(
        custom_responder=lambda _i, _p, s: s.model_validate_json(payload)
    )


def test_qareport_maps_dimensions_and_legacy_fields(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    good = EvalRubric.mock_response(_KEYS)
    report = evaluate_clip_qa(
        tmp_repo, default_cfg, _vlm(good), shot, _run(tmp_repo, shot.id)
    )
    assert report.passed and len(report.dimension_scores) == 11
    assert report.identity_scores == {"Pip": 0.91} and report.steps_done == {"1": True}
    assert report.eval_overall is not None and report.eval_overall > 0.9
    assert report.rubric_version.startswith("video-eval-v1/")


def test_unscripted_character_blocks_via_defect_gate(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    script = ScriptVerdict(
        unscripted_characters=["Cat"], evidence="cat enters at t=1.50s"
    )
    bad = EvalRubric.mock_response(_KEYS).model_copy(update={"script": script})
    report = evaluate_clip_qa(
        tmp_repo, default_cfg, _vlm(bad), shot, _run(tmp_repo, shot.id)
    )
    assert not report.passed
    [d] = [d for d in report.defects if d.type == "unscripted_character"]
    assert (d.severity, d.subject) == ("high", "Cat")
    dim = next(s for s in report.dimension_scores if s.dimension == "script_adherence")
    # script_adherence is not a hard gate after golden-v1 calibration; the HIGH defect blocks
    assert not dim.hard_gate and dim.score < 1.0
    assert any("unscripted_character" in r for r in report.failure_reasons)

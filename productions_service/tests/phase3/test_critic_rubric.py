"""Phase 3 critic: deterministic gating, hard-cut detection, identity scores, spec-only rubric."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import seed_valid_graph
from storygraph.adapters.media_frames import probe_clip
from storygraph.adapters.mock import MockVLMProvider
from storygraph.agents.critic import evaluate_clip_qa
from storygraph.config import Config
from storygraph.qa.critic.checks import CriticThresholds, MediaSignals, check_cuts
from storygraph.qa.critic.gate import evaluate_rubric, gate
from storygraph.qa.critic.prompt import build_critic_prompt
from storygraph.qa.critic.rubric import ClipRubric
from storygraph.qa.critic.spec import parse_compiled_spec
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, Role, Status

SPEC = {
    "task": "render_video_clip",
    "clip": {"duration_s": 8.0, "aspect": "16:9", "fps": 24, "audio": {}},
    "subjects": [
        {
            "id": "S1",
            "name": "Arjun",
            "kind": "person",
            "ref_image": "IMAGE_REF_1",
            "screen_pos": "center",
            "framing": "MS",
            "can_speak": True,
            "has_mouth": True,
        },
    ],
    "setting": {"id": "L1", "name": "Cafe", "ref_image": "IMAGE_REF_2"},
    "objects": [
        {
            "id": "O1",
            "name": "Brass Compass",
            "start": {"where": "on the table"},
            "end": {"held_by": "S1"},
            "moves": True,
        },
    ],
    "camera": {"size": "MS", "angle": "eye", "move": "static", "lens_mm": 35},
    "sequence": [
        {"n": 1, "actor": "S1", "verb": "picks up", "target": "O1"},
        {
            "n": 2,
            "actor": "S1",
            "verb": "studies",
            "target": "O1",
            "end_state": "compass held at chest",
        },
    ],
    "speech": [
        {
            "after": 1,
            "speaker": "S1",
            "lang": "en",
            "text": "The compass points north.",
            "voice": "v1",
            "lipsync": True,
        },
    ],
    "constraints": ["single_continuous_take"],
}
_GOOD = ClipRubric.mock_response(
    'RUBRIC_KEYS={"steps":[1,2],"subjects":["Arjun"],"objects":["Brass Compass"],'
    '"speakers":["Arjun"],"continuity":false}'
)


def _thr(cfg: Config) -> CriticThresholds:
    return CriticThresholds.from_cfg(cfg.qa)


def _add_run(repo: Repo, shot_id: str, attempt: int) -> GenerationRun:
    uri = repo.blobs.put_bytes(f"clips/a{attempt}.mp4", b"mp4", "video/mp4")
    return repo.add_generation_run(
        GenerationRun(
            id=f"run_a{attempt}",
            created_by=Role.PIPELINE,
            status=Status.RENDERED,
            shot_id=shot_id,
            attempt=attempt,
            provider="mock",
            model="mock",
            compiled_prompt=json.dumps(SPEC),
            seed=attempt,
            package_hash="h",
            output_video_uri=uri,
        )
    )


def _scripted_vlm(rubric: ClipRubric) -> MockVLMProvider:
    payload = rubric.model_dump_json()
    return MockVLMProvider(
        custom_responder=lambda _i, _p, s: s.model_validate_json(payload)
    )


def test_drift_flag_blocks_even_with_perfect_scores(default_cfg: Config) -> None:
    spec = parse_compiled_spec(json.dumps(SPEC))
    rubric = _GOOD.model_copy(update={"drift_flags": ["character_design_drift"]})
    outcome = evaluate_rubric(spec, rubric, MediaSignals(), _thr(default_cfg))
    assert outcome.scores["action_achieved"] == 1.0
    decision = gate(outcome.defects, _thr(default_cfg))
    assert not decision.passed
    assert any("character_design_drift" in r for r in decision.failure_reasons)
    clean = gate(
        evaluate_rubric(spec, _GOOD, MediaSignals(), _thr(default_cfg)).defects,
        _thr(default_cfg),
    )
    assert clean.passed and clean.failure_reasons == []


def test_spec_conflict_routes_to_spec_and_recompile(default_cfg: Config) -> None:
    spec = parse_compiled_spec(json.dumps(SPEC))
    steps = [
        s.model_copy(
            update={
                "done": s.n != 2,
                "spec_conflict": s.n == 2,
                "evidence": "t=4-8s compass stays on table",
            }
        )
        for s in _GOOD.steps
    ]
    outcome = evaluate_rubric(
        spec,
        _GOOD.model_copy(update={"steps": steps}),
        MediaSignals(),
        _thr(default_cfg),
    )
    [d] = [d for d in outcome.defects if d.type == "step_not_done"]
    assert (d.severity, d.likely_cause, d.subject) == ("high", "spec", "Arjun")
    assert gate(outcome.defects, _thr(default_cfg)).suggested_fix == "recompile_prompt"


def _color_clip(path: Path, color: str, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=160x90:r=24:d={seconds}",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(path),
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=60,
    )


@pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg"
)
def test_hard_cut_detected_in_two_segment_video(
    tmp_path: Path, default_cfg: Config
) -> None:
    _color_clip(tmp_path / "a.mp4", "red", 1.5)
    _color_clip(tmp_path / "b.mp4", "blue", 1.5)
    (tmp_path / "list.txt").write_text("file 'a.mp4'\nfile 'b.mp4'\n")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(tmp_path / "list.txt"),
            "-c",
            "copy",
            str(tmp_path / "cut.mp4"),
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=60,
    )
    probe = probe_clip((tmp_path / "cut.mp4").read_bytes())
    assert len(probe.cut_times_s) == 1 and abs(probe.cut_times_s[0] - 1.5) < 0.2
    assert len(probe.frames) >= 12 and probe.frames[0].t_s == 0.0
    single = probe_clip((tmp_path / "a.mp4").read_bytes())
    assert single.cut_times_s == ()
    spec = parse_compiled_spec(json.dumps(SPEC))
    sig = MediaSignals(duration_s=probe.duration_s, cut_times_s=probe.cut_times_s)
    defects, cuts = check_cuts(spec, _GOOD, sig, _thr(default_cfg))
    assert [d.type for d in defects] == ["hard_cut"] and cuts == list(probe.cut_times_s)


def test_identity_scores_populated_and_missing_subject_blocks(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    scored = _GOOD.model_copy(
        update={"identities": [_GOOD.identities[0].model_copy(update={"score": 85.0})]}
    )
    report = evaluate_clip_qa(
        tmp_repo,
        default_cfg,
        _scripted_vlm(scored),
        shot,
        _add_run(tmp_repo, shot.id, 1),
    )
    assert report.passed and report.face_similarity == {"char_arjun": 0.85}
    assert report.identity_scores == {"Arjun": 0.85}
    missing = _GOOD.model_copy(update={"identities": []})
    blocked = evaluate_clip_qa(
        tmp_repo,
        default_cfg,
        _scripted_vlm(missing),
        shot,
        _add_run(tmp_repo, shot.id, 2),
    )
    assert not blocked.passed and blocked.identity_scores == {"Arjun": 0.0}
    assert [d.type for d in blocked.defects] == ["identity_unverified"]


def test_rubric_judges_spec_steps_only(default_cfg: Config) -> None:
    spec = parse_compiled_spec(json.dumps(SPEC))
    prompt = build_critic_prompt(
        "shot_1", spec, ["CLIP FRAME t=0.00s"], False, "RUBRIC"
    )
    assert "1. Arjun picks up Brass Compass" in prompt
    assert "Arjun checks the compass." not in prompt and "attempt" not in prompt.lower()
    foreign = _GOOD.model_copy(
        update={
            "steps": [
                _GOOD.steps[0],
                _GOOD.steps[0].model_copy(update={"n": 99, "done": False}),
            ]
        }
    )
    outcome = evaluate_rubric(spec, foreign, MediaSignals(), _thr(default_cfg))
    assert outcome.steps_done == {"1": True, "2": False}
    assert [d.type for d in outcome.defects] == ["step_unverified"]


def test_same_verdict_on_first_and_late_attempts(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    shot = seed_valid_graph(tmp_repo)
    borderline = _GOOD.model_copy(
        update={"identities": [_GOOD.identities[0].model_copy(update={"score": 0.6})]}
    )
    vlm = _scripted_vlm(borderline)
    first = evaluate_clip_qa(
        tmp_repo, default_cfg, vlm, shot, _add_run(tmp_repo, shot.id, 1)
    )
    late = evaluate_clip_qa(
        tmp_repo, default_cfg, vlm, shot, _add_run(tmp_repo, shot.id, 5)
    )
    assert not first.passed and not late.passed
    assert (
        first.defects == late.defects and first.failure_reasons == late.failure_reasons
    )
    assert vlm.calls[0]["prompt"] == vlm.calls[1]["prompt"]

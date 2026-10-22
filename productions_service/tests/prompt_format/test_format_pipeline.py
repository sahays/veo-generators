"""Prompt-format plumbing: config switch, spec-vs-text storage, eval reads the spec,
fallback rebinding re-renders hybrid text, and spec-content lint (end states / holders)."""

from __future__ import annotations

import re

from hybrid_spec_seed import key_spec
from omni_seed import _seed_shots
from storygraph.adapters.omni.fallback import build_ladder
from storygraph.adapters.omni.package import RefLabel, RenderPackage
from storygraph.adapters.omni.safety import select_safety_profile
from storygraph.budget import select_references
from storygraph.compile import compile_shot
from storygraph.config import Config
from storygraph.lint.content_rules import end_state_issues, holder_issues
from storygraph.omni.render import parse_spec
from storygraph.omni.render_hybrid import SINGLE_TAKE, render_hybrid
from storygraph.omni.spec import ObjectSpec, ObjectState, StepSpec
from storygraph.qa.critic.spec import parse_compiled_spec
from storygraph.repo import Repo
from storygraph.repo.prompt_versions import PromptDraft, PromptVersionRepo
from storygraph.schema import GenerationRun, Role
from storygraph.views import shot_view

_LABELS = (
    RefLabel("gs://b/pip.png", "a_pip", ("Pip",), "character"),
    RefLabel("gs://b/ava.png", "a_ava", ("Ava",), "character"),
    RefLabel("gs://b/shop.png", "a_shop", ("Small Workshop",), "location"),
    RefLabel("gs://b/key.png", "a_key", ("Brass Key",), "prop"),
)


def _with_format(cfg: Config, fmt: str) -> Config:
    return cfg.model_copy(
        update={"video": cfg.video.model_copy(update={"prompt_format": fmt})}
    )


def test_config_switch_keeps_one_spec_and_changes_only_the_sent_text(
    tmp_repo: Repo, default_cfg: Config
) -> None:
    assert default_cfg.video.prompt_format == "hybrid"
    _seed_shots(tmp_repo)
    view = shot_view(tmp_repo, "shot_1")
    plan = select_references(view, default_cfg, repo=tmp_repo)
    hybrid = compile_shot(view, plan, default_cfg)
    legacy = compile_shot(view, plan, _with_format(default_cfg, "json"))
    spec = parse_spec(hybrid.spec_json)
    assert spec is not None and hybrid.spec_json == legacy.spec_json
    assert hybrid.compiled_prompt == render_hybrid(spec)
    assert hybrid.compiled_prompt.startswith(SINGLE_TAKE)
    assert legacy.compiled_prompt == legacy.spec_json
    assert hybrid.package_hash != legacy.package_hash


def _run(**kw: object) -> GenerationRun:
    base: dict[str, object] = {
        "id": "run_1",
        "created_by": Role.PIPELINE,
        "shot_id": "shot_1",
        "attempt": 1,
        "provider": "mock",
        "model": "omni",
        "compiled_prompt": render_hybrid(key_spec()),
        "seed": 1,
        "package_hash": "h",
    }
    return GenerationRun.model_validate(base | kw)


def test_eval_reads_expectations_from_the_spec_not_the_prose(tmp_repo: Repo) -> None:
    spec_json = key_spec().render()
    versions = PromptVersionRepo(tmp_repo.store)
    pv = versions.create(PromptDraft(shot_id="shot_1", spec_json=spec_json))
    for run in (_run(spec_json=spec_json), _run(prompt_version_id=pv.id)):
        expected = parse_compiled_spec(versions.spec_for_run(run))
        assert expected.parsed and [o.name for o in expected.objects] == [
            "Brass Key",
            "Workbench",
        ]
    assert not parse_compiled_spec(_run().compiled_prompt).parsed


def _hybrid_package() -> RenderPackage:
    spec = key_spec()
    return RenderPackage(
        shot_id="shot_1",
        compiled_prompt=render_hybrid(spec),
        negative_prompt="",
        reference_asset_ids=[lbl.asset_id for lbl in _LABELS],
        reference_uris=[lbl.uri for lbl in _LABELS],
        first_frame_asset_id="a_ff",
        first_frame_uri="gs://b/prev.png",
        duration_s=8.0,
        aspect_ratio="16:9",
        seed=1,
        package_hash="h",
        spec_json=spec.render(),
        prompt_format="hybrid",
        reference_labels=_LABELS,
    )


def test_every_fallback_rung_rerenders_hybrid_text_for_the_images_it_sends() -> None:
    pkg = _hybrid_package()
    ladder = build_ladder(pkg, select_safety_profile("", ""), 6, "tag")
    primary_body = ladder[0].request.blocks[0]["text"].split("\n", 1)[1]
    assert primary_body == pkg.compiled_prompt  # primary rung sends the stored text
    for step in ladder:
        text = step.request.blocks[0]["text"]
        header = text.split("\n", 1)[0] if text.startswith("[#") else ""
        body = text[len(header) :].lstrip("\n")
        assert body.startswith(SINGLE_TAKE)
        sent = set(re.findall(r"<(IMAGE_REF_\d+)>@Image", header))
        assert set(re.findall(r"<(IMAGE_REF_\d+)>", body)) == sent
        assert ("<FIRST_FRAME>" in body) == step.request.first_frame_bound
    assert "Pip <IMAGE_REF_0>" in ladder[1].request.blocks[0]["text"]


def _key(end: ObjectState) -> ObjectSpec:
    return ObjectSpec(
        id="O1",
        name="Brass Key",
        start=ObjectState(where="on the Workbench"),
        end=end,
        moves=True,
    )


def test_end_state_lint_flags_holder_contradicting_the_last_beat() -> None:
    held = key_spec(objects=[_key(ObjectState(held_by="S1"))])
    issues = end_state_issues(held, "shot_1")
    assert [(i.code, i.severity) for i in issues] == [
        ("S2_CLIP_LINT_END_STATE_CONTRADICTS_BEAT", "error")
    ]
    assert end_state_issues(key_spec(), "shot_1") == []


def test_end_state_lint_flags_state_change_without_a_causing_beat() -> None:
    idle = [StepSpec(n=1, actor="S1", verb="waves at Ava")]
    spec = key_spec(sequence=idle, speech=None)
    codes = [i.code for i in end_state_issues(spec, "shot_1")]
    assert codes == ["S2_CLIP_LINT_END_STATE_WITHOUT_BEAT"]


def test_holder_lint_flags_object_both_held_and_placed() -> None:
    spec = key_spec(
        objects=[_key(ObjectState(held_by="S1", where="inside the drawer"))]
    )
    assert [i.code for i in holder_issues(spec, "shot_1")] == [
        "S2_CLIP_LINT_HOLDER_CONFLICT"
    ]

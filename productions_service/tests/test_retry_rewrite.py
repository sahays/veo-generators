"""Retry feedback must describe the desired outcome, never the failure (review item 4)."""

from __future__ import annotations

import re

from conftest import seed_valid_graph
from storygraph.pipeline.render_stage import _collect_retry_context
from storygraph.qa.retry_rewrite import (
    PropFocus,
    RewriteContext,
    context_from_view,
    rewrite_retry_feedback,
)
from storygraph.repo import Repo
from storygraph.schema import GenerationRun, QAReport, Role, Status
from storygraph.views import shot_view

_NEGATIVE = re.compile(
    r"vanish|disappear|duplicat|never|missing|remains hanging|\bnot\b|\bno\b",
    re.IGNORECASE,
)


def _kitchen_ctx() -> RewriteContext:
    return RewriteContext(
        actors=("Pip", "Milo"),
        props=(
            PropFocus("Kitchen Towel", handler="Pip", origin="the wall peg"),
            PropFocus("Wooden Chair"),
        ),
        sides=(("Pip", "center"), ("Milo", "right")),
        actor_keys={
            "char_pip": "Pip",
            "pip": "Pip",
            "char_milo": "Milo",
            "milo": "Milo",
        },
    )


def test_towel_failure_becomes_named_target_state_without_failure_words() -> None:
    report = QAReport(
        passed=False,
        failure_reasons=[
            "The kitchen towel remains hanging in the background while Pip holds another"
        ],
        artifact_flags=[
            "duplicate_prop",
            "object_vanished",
            "duplicate_character_milo",
            "spatial_axis_flip",
            "start_frame_bleed",
        ],
    )
    out = rewrite_retry_feedback(report, _kitchen_ctx())
    assert len(out) == 4  # deduped (reason + flag collapse) and capped
    assert out[0] == (
        "after Pip takes the Kitchen Towel, the wall peg is empty; "
        "exactly one Kitchen Towel, in Pip's hands"
    )
    assert any("exactly one Milo on screen" in s for s in out)
    assert any(
        "Pip stays at center" in s and "Milo stays screen-right" in s for s in out
    )
    assert not [s for s in out if _NEGATIVE.search(s)]
    assert all("Wooden Chair" not in s for s in out[:2])  # focus follows the named prop


def test_unclassified_reason_uses_llm_only_when_output_is_positive() -> None:
    report = QAReport(passed=False, failure_reasons=["Pacing feels off in the middle"])
    ctx = _kitchen_ctx()
    assert rewrite_retry_feedback(report, ctx) == [
        "the action above plays out completely, clearly and in order on screen"
    ]
    good = rewrite_retry_feedback(
        report, ctx, llm=lambda r, c: "Pip crosses at a steady walk"
    )
    assert good == ["Pip crosses at a steady walk"]
    bad = rewrite_retry_feedback(report, ctx, llm=lambda r, c: "Pip does not stop")
    assert bad == []


def test_context_from_view_resolves_holder_and_flag_actor_suffix(
    tmp_repo: Repo,
) -> None:
    seed_valid_graph(tmp_repo)
    ctx = context_from_view(shot_view(tmp_repo, "shot_1"))
    assert ctx.props[0].name == "Brass Compass" and ctx.props[0].handler == "Arjun"
    report = QAReport(
        passed=False, artifact_flags=["object_vanished", "missing_character_char_arjun"]
    )
    assert rewrite_retry_feedback(report, ctx) == [
        "the Brass Compass stays in Arjun's hands and in view for the whole shot",
        "Arjun is clearly on screen for the whole shot",
    ]


def test_render_stage_retry_context_feeds_rewritten_targets(tmp_repo: Repo) -> None:
    seed_valid_graph(tmp_repo)
    tmp_repo.add_generation_run(
        GenerationRun(
            id="run_shot_1_1",
            created_by=Role.PIPELINE,
            status=Status.FAILED,
            shot_id="shot_1",
            attempt=1,
            provider="mock",
            model="mock",
            compiled_prompt="p",
            seed=1,
            package_hash="h",
            qa_scores=QAReport(
                passed=False,
                failure_reasons=["The brass compass disappears halfway through"],
                artifact_flags=["object_vanished", "duplicate_prop"],
            ),
        )
    )
    feedback, allow_comp = _collect_retry_context(
        tmp_repo, shot_view(tmp_repo, "shot_1")
    )
    assert feedback[0].startswith("the Brass Compass stays in Arjun's hands")
    assert not [s for s in feedback if _NEGATIVE.search(s)]
    assert allow_comp is False  # duplicate_prop still disables composites

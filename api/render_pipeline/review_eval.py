"""Stages 1 and 4: Storyboard review and multimodal finished video evaluation."""

from __future__ import annotations

from typing import Any

import deps
from cost_tracking import accumulate_text_cost_on
from models import ProjectStatus
from render_pipeline.state import _ensure_steps_list, _update_pipeline_step


async def run_storyboard_review_step(
    production_id: str,
    production: Any = None,
    steps: list[dict[str, Any]] | None = None,
) -> Any:
    """Stage 1: Audit storyboard continuity, speaker attribution, and prop physics."""
    production = production or deps.firestore_svc.get_production(production_id)
    if not production:
        return None
    steps = (
        steps if steps is not None else _ensure_steps_list(production, auto_review=True)
    )
    msg = "Auditing storyboard continuity, speaker lip-sync & physics..."
    _update_pipeline_step(
        production_id,
        steps,
        "review_storyboard",
        "running",
        msg,
        extra_updates={"status": ProjectStatus.REVIEWING},
    )
    res = await deps.ai_svc.review_storyboard(production_id, production)
    u = res.usage
    accumulate_text_cost_on(
        "production",
        production_id,
        u.cost_usd,
        u.input_tokens,
        u.output_tokens,
        u.model_name,
    )
    report, continuity, scenes = (
        res.data["review_report"],
        res.data.get("continuity"),
        res.data.get("scenes") or production.scenes,
    )
    production.scenes = scenes
    if continuity is not None:
        production.continuity = continuity
    production.review_report = report
    extra: dict[str, Any] = {
        "scenes": [s.dict() for s in scenes],
        "review_report": report.dict(),
    }
    if continuity is not None:
        extra["continuity"] = continuity.dict()
    detail = f"Score {report.overall_score}/100 • Fixed {len(report.issues)} issue(s) • {u.input_tokens:,} in / {u.output_tokens:,} out tokens (${u.cost_usd:.4f})"
    _update_pipeline_step(
        production_id,
        steps,
        "review_storyboard",
        "completed",
        detail=detail,
        usage=u,
        extra_updates=extra,
    )
    return res


def _apply_eval_findings_to_scenes(production: Any, eval_report: Any) -> None:
    """Tag each scene as 'flagged' or 'passed' based on evaluation findings."""
    for idx, scene in enumerate(production.scenes):
        matched = next(
            (
                f
                for f in eval_report.findings
                if f.scene_id == scene.id or f.scene_number == idx + 1
            ),
            None,
        )
        if matched is not None:
            scene.eval_status = "flagged"
            scene.eval_feedback = matched.observed_issue
        else:
            scene.eval_status = "passed"


async def run_video_eval_step(
    production_id: str,
    production: Any = None,
    stitched_uri: str | None = None,
    iteration: int = 1,
    steps: list[dict[str, Any]] | None = None,
) -> Any:
    """Stage 4: Multimodal evaluation of the finished stitched video against the storyboard."""
    production = production or deps.firestore_svc.get_production(production_id)
    if not production:
        return None
    steps = (
        steps if steps is not None else _ensure_steps_list(production, auto_eval=True)
    )
    _update_pipeline_step(
        production_id,
        steps,
        "evaluate_video",
        "running",
        "Evaluating finished video for continuity, lip-sync & physical realism...",
        extra_updates={"status": ProjectStatus.EVALUATING},
    )
    eval_res = await deps.ai_svc.evaluate_finished_video(
        production_id, production, video_gcs_uri=stitched_uri, iteration=iteration
    )
    u = eval_res.usage
    accumulate_text_cost_on(
        "production",
        production_id,
        u.cost_usd,
        u.input_tokens,
        u.output_tokens,
        u.model_name,
    )
    eval_report = eval_res.data["eval_report"]
    _apply_eval_findings_to_scenes(production, eval_report)
    production.eval_report = eval_report
    status_str = (
        "PASSED"
        if eval_report.passed
        else f"Flagged {len(eval_report.findings)} scene(s)"
    )
    detail = (
        f"Score {eval_report.overall_score}/100 ({status_str}) • "
        f"{u.input_tokens:,} in / {u.output_tokens:,} out tokens (${u.cost_usd:.4f})"
    )
    extra = {
        "scenes": [s.dict() for s in production.scenes],
        "eval_report": eval_report.dict(),
    }
    _update_pipeline_step(
        production_id,
        steps,
        "evaluate_video",
        "completed",
        detail=detail,
        usage=u,
        extra_updates=extra,
    )
    return eval_report

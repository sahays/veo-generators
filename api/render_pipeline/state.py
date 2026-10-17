"""Pipeline state management, step logging, and Responsible AI prompt sanitization."""

from __future__ import annotations

from datetime import datetime
import os
import sys
from typing import Any, Callable

import deps
from helpers import parse_timestamp
from models import PipelineStepLog, ProjectStatus, UsageMetrics

DEFAULT_IMAGE_CONCURRENCY = 4
DEFAULT_VIDEO_CONCURRENCY = 4


def get_hook(name: str, default: Callable[..., Any]) -> Callable[..., Any]:
    """Resolve an overridable helper from `routers.render_helpers` if loaded."""
    mod = sys.modules.get("routers.render_helpers")
    return getattr(mod, name, default) if mod is not None else default


def log_extra(where: str, what: str, why: str, how: str) -> dict[str, str]:
    """Build structured 5W1H context dictionary for semantic logging."""
    return {
        "who": "render_pipeline",
        "where": where,
        "what": what,
        "why": why,
        "how": how,
    }


def _image_concurrency() -> int:
    """Return bounded concurrency for keyframe generation."""
    val = os.getenv("RENDER_IMAGE_CONCURRENCY", str(DEFAULT_IMAGE_CONCURRENCY))
    return max(1, int(val))


def _video_concurrency() -> int:
    """Return bounded concurrency for scene video generation."""
    val = os.getenv("RENDER_VIDEO_CONCURRENCY", str(DEFAULT_VIDEO_CONCURRENCY))
    return max(1, int(val))


def _scene_duration_seconds(scene: Any) -> int:
    """Veo billing duration: clipped into [4, 8]; defaults to 8 on parse error."""
    try:
        start = parse_timestamp(scene.timestamp_start)
        end = parse_timestamp(scene.timestamp_end)
        return max(4, min(8, int(end - start)))
    except (ValueError, IndexError):
        return 8


def build_initial_pipeline_steps(
    auto_review: bool = True, auto_eval: bool = True
) -> list[dict[str, Any]]:
    """Create initial PipelineStepLog entries for the 5-stage render pipeline."""
    specs = [
        ("review_storyboard", "Storyboard Continuity & Realism Review", auto_review),
        ("generate_frames", "Start & End Keyframe Generation", True),
        ("generate_videos", "Scene Video Generation", True),
        ("stitch_video", "Video Transcoding & Stitching", True),
        ("evaluate_video", "Multimodal Finished-Video Evaluation", auto_eval),
        ("regenerate_scenes", "Selective Auto-Regeneration & Re-Stitch", auto_eval),
    ]
    return [
        PipelineStepLog(
            step_id=sid, label=label, status="pending" if enabled else "skipped"
        ).dict()
        for sid, label, enabled in specs
    ]


def _ensure_steps_list(
    production: Any, auto_review: bool = True, auto_eval: bool = True
) -> list[dict[str, Any]]:
    """Return existing pipeline steps as dicts or initialize defaults."""
    raw_steps = getattr(production, "pipeline_steps", None) or []
    if not raw_steps:
        return build_initial_pipeline_steps(
            auto_review=auto_review, auto_eval=auto_eval
        )
    return [s.dict() if hasattr(s, "dict") else dict(s) for s in raw_steps]


def _apply_step_mutation(
    step: dict[str, Any],
    status: str,
    detail: str,
    usage: UsageMetrics | None,
    now: datetime,
) -> None:
    """Mutate a single pipeline step dictionary in-place."""
    step["status"] = status
    if status == "running" and not step.get("started_at"):
        step["started_at"] = now
    if status in ("completed", "skipped", "failed"):
        step["completed_at"] = now
    if detail:
        step["detail"] = detail
    if usage is not None:
        step["usage"] = usage.dict() if hasattr(usage, "dict") else usage


def _update_pipeline_step(
    production_id: str,
    steps: list[dict[str, Any]],
    step_id: str,
    status: str,
    detail: str = "",
    usage: UsageMetrics | None = None,
    extra_updates: dict[str, Any] | None = None,
) -> None:
    """Update a step in `steps` and persist pipeline progress to Firestore."""
    now = datetime.utcnow()
    for step in steps:
        if step.get("step_id") == step_id:
            _apply_step_mutation(step, status, detail, usage, now)
            break
    if deps.firestore_svc:
        payload = {
            "pipeline_stage": step_id,
            "pipeline_steps": steps,
            **(extra_updates or {}),
        }
        deps.firestore_svc.update_production(production_id, payload)


def _fail_production(
    production_id: str,
    error_message: str,
    steps: list[dict[str, Any]] | None = None,
) -> None:
    """Mark production and any running pipeline steps as failed in Firestore."""
    payload: dict[str, Any] = {
        "status": ProjectStatus.FAILED,
        "error_message": error_message,
    }
    if steps is not None:
        now = datetime.utcnow()
        for step in steps:
            if step.get("status") == "running":
                step["status"] = "failed"
                step["completed_at"] = now
                step["detail"] = step.get("detail") or error_message
        payload["pipeline_steps"] = steps
        payload["pipeline_stage"] = "failed"
    deps.firestore_svc.update_production(production_id, payload)


def _fail_scene(production_id: str, scene_id: str, error: Exception | str) -> None:
    """Mark a single scene as failed in Firestore."""
    deps.firestore_svc.update_scene(
        production_id,
        scene_id,
        {"status": "failed", "error_message": str(error)},
    )


_RAI_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Chibi", "Stylized 3D animated"),
    ("chibi", "stylized 3D animated"),
    ("burning palace", "dramatically lit palace"),
    ("burning", "warmly illuminated"),
    ("burn", "illuminate"),
    ("blazes", "glows brightly"),
    ("blazing", "radiantly glowing"),
    ("blaze", "radiant glow"),
    ("ignites", "shimmers with light"),
    ("ignite", "shimmer with golden light"),
    ("ignited", "illuminated"),
    ("roaring orange flames", "dramatic golden-amber light"),
    ("roaring flames", "golden-amber radiance"),
    ("flames", "golden-orange light"),
    ("flame", "warm golden light"),
    ("on fire", "bathed in dramatic amber glow"),
    ("cotton-candy fire", "whimsical pastel light"),
    ("fire", "warm amber glow"),
    ("smoke clouds", "magical aurora mist"),
    ("smoke", "luminous mist"),
    ("embers", "golden sparkles"),
    ("sparks", "starlight sparkles"),
    ("destruction", "dramatic transformation"),
    ("destroyed", "transformed"),
    ("explosion", "burst of golden light"),
    ("battlefield", "epic mythic arena"),
    ("blood", "crimson dust"),
    ("kill", "defeat"),
    ("killing", "overcoming"),
    ("attack", "confront"),
    ("attacking", "confronting"),
    ("weapon", "ornate ceremonial staff"),
    ("weapons", "ornate ceremonial artifacts"),
)

_RAI_NARRATION_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("अग्नि", "दिव्य ज्योति"),
    ("आग", "दिव्य आभा"),
    ("भस्म कर दिया", "प्रकाशमान कर दिया"),
    ("भस्म", "उज्ज्वल"),
    ("लंका का काल", "लंका में हलचल"),
    ("काल", "तेज"),
    ("जला", "चमका"),
    ("दहन", "प्रकाश"),
)


def _is_rai_blocked_error(err: Exception | str | None) -> bool:
    """Return True if an exception/error string indicates a Responsible AI block."""
    if not err:
        return False
    text = str(err).lower()
    markers = (
        "content_blocked",
        "responsible ai",
        "violates google",
        "safety",
        "blocked",
    )
    return any(m in text for m in markers)


def _sanitize_text_for_rai(text: str) -> str:
    """Replace sensitive battle/fire terms with theatrical equivalents."""
    out = text or ""
    for src, target in _RAI_REPLACEMENTS:
        out = out.replace(src, target).replace(src.capitalize(), target.capitalize())
    return out


def _sanitize_continuity_for_rai(production: Any) -> None:
    """Sanitize production continuity setting and character descriptions in-place."""
    if not (production and getattr(production, "continuity", None)):
        return
    if production.continuity.setting_notes:
        production.continuity.setting_notes = _sanitize_text_for_rai(
            production.continuity.setting_notes
        )
    for ch in production.continuity.characters or []:
        if ch.description:
            ch.description = _sanitize_text_for_rai(ch.description)


def _sanitize_scene_for_rai(scene: Any, production: Any = None) -> str:
    """Soften intense battle/fire/destruction phrasing into theatrical RAI-safe wording."""
    desc = _sanitize_text_for_rai(scene.visual_description or "")
    suffix = " Theatrical, family-friendly mythological stage drama with warm cinematic lighting."
    if suffix.strip() not in desc:
        desc = desc.rstrip(". ") + "." + suffix
    scene.visual_description = desc
    if getattr(scene, "narration", None):
        narr = scene.narration
        for src, target in _RAI_NARRATION_REPLACEMENTS:
            narr = narr.replace(src, target)
        scene.narration = _sanitize_text_for_rai(narr)
    _sanitize_continuity_for_rai(production)
    return desc

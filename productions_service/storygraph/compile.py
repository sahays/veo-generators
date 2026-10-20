"""Deterministic shot compiler (`compile_shot`): typed `OmniClipSpec` rendered as compact JSON."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from .budget import RefPlan
from .clips.prompt_ctx import resolve_shot_clip
from .config import Config, VideoProviderCfg
from .omni.builder import DESC_LEVELS, build_spec
from .omni.symbols import ImageBindings
from .repair.models import RepairDirective
from .views import ShotView

OMNI_TARGET_CHARS: Final[int] = 3500
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Package:
    shot_id: str
    compiled_prompt: str
    negative_prompt: str
    reference_asset_ids: list[str]
    reference_uris: list[str]
    first_frame_asset_id: str | None
    first_frame_uri: str | None
    duration_s: float
    aspect_ratio: str
    seed: int
    package_hash: str
    resolution: str = "360p"
    dropped_to_verbal: list[str] = field(default_factory=list)


def _derive_seed(project_id: str, shot_id: str, attempt: int = 1) -> int:
    digest = hashlib.sha256(f"{project_id}:{shot_id}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF


def image_bindings(
    view: ShotView, plan: RefPlan, caps: VideoProviderCfg
) -> ImageBindings:
    """Bind entities to the exact `IMAGE_REF_k` / `FIRST_FRAME` roles the Omni adapter sends."""
    # Imported lazily: the adapter modules import `Package` from this module.
    from .adapters.omni.inputs import plan_image_slots
    from .adapters.omni.package import build_ref_labels

    slots = plan_image_slots(
        list(build_ref_labels(view, plan.selected_assets)),
        plan.first_frame.uri if plan.first_frame else None,
        caps.max_reference_images or 3,
        caps.first_frame_mode,
    )
    depicts = {a.id: a.depicts_entity_ids for a in plan.selected_assets}
    by_entity: dict[str, str] = {}
    for asset_id, token in slots.ref_tokens().items():
        for eid in depicts.get(asset_id, []):
            by_entity.setdefault(eid, token)
    return ImageBindings(bool(slots.first_frame_uri), by_entity)


def _log_budget(view: ShotView, event: str, what: str, why: str, how: str) -> None:
    _log.info(
        event,
        extra={
            "who": "storygraph.compile",
            "where": f"compile_shot:{view.shot.id}",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
        },
    )


def _render_within_budget(
    view: ShotView,
    bindings: ImageBindings,
    max_chars: int | None = None,
    retry_feedback: list[str] | None = None,
    repair: RepairDirective | None = None,
) -> str:
    """Render the spec, trimming identity/extras level by level (never sequence/speech)."""
    budget = max_chars or OMNI_TARGET_CHARS
    clip = resolve_shot_clip(view.scene, view.shot)
    extra = tuple(repair.constraint_tokens) if repair else ()
    first_level = min(repair.min_desc_level if repair else 0, len(DESC_LEVELS) - 1)
    prompt = ""
    for level in range(first_level, len(DESC_LEVELS)):
        policy = DESC_LEVELS[level]
        prompt = build_spec(
            view, clip, bindings, policy, retry_feedback, extra
        ).render()
        if len(prompt) <= budget:
            return prompt
        _log_budget(
            view,
            "omni_spec_trimmed",
            "description level exceeded soft budget",
            f"{len(prompt)} > {budget} chars",
            f"DESC_LEVELS {level} -> {level + 1}",
        )
    _log_budget(
        view,
        "omni_spec_over_budget",
        "spec still over soft budget at minimum description level",
        f"{len(prompt)} > {budget} chars (sequence/speech are never trimmed)",
        "sent as-is",
    )
    return prompt


def _compute_package_hash(
    view: ShotView,
    plan: RefPlan,
    prompt: str,
    negative_prompt: str,
    seed: int,
    resolution: str = "360p",
) -> str:
    look_dict = view.shot.look.model_dump() if view.shot.look else None
    clip = resolve_shot_clip(view.scene, view.shot)
    canonical_payload = json.dumps(
        {
            "shot_id": view.shot.id,
            "omni_spec": prompt,
            "negative_prompt": negative_prompt,
            "ref_shas": [a.sha256 for a in plan.selected_assets],
            "first_frame_sha": plan.first_frame.sha256 if plan.first_frame else None,
            "duration_s": view.shot.duration_s,
            "aspect_ratio": view.style_guide.aspect_ratio,
            "resolution": resolution,
            "seed": seed,
            "look": look_dict,
            "clip_index": clip.clip_index,
            "omni_prompt": clip.omni_prompt,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _repair_view(view: ShotView, repair: RepairDirective | None) -> ShotView:
    """Apply render-only repair levers to the view (static camera); story is untouched."""
    if repair is None or not repair.lock_camera_static:
        return view
    shot = view.shot
    look = (
        shot.look.model_copy(update={"camera_motion_intent": ""}) if shot.look else None
    )
    camera = shot.camera.model_copy(update={"movement": "static"})
    return view.model_copy(
        update={"shot": shot.model_copy(update={"camera": camera, "look": look})}
    )


def _merge_targets(
    retry_feedback: list[str] | None, repair: RepairDirective | None
) -> list[str] | None:
    merged = [*(retry_feedback or []), *(repair.must_achieve if repair else [])]
    return list(dict.fromkeys(merged)) or None


def compile_shot(
    view: ShotView,
    plan: RefPlan,
    cfg: Config,
    caps: VideoProviderCfg | None = None,
    project_id: str = "default",
    attempt: int = 1,
    retry_feedback: list[str] | None = None,
    resolution: str = "360p",
    repair: RepairDirective | None = None,
) -> Package:
    """Render the deterministic Omni spec package from ShotView + RefPlan within the budget.

    `repair` (QA repair attempt) adds positive constraint tokens and targets, starts the
    budget walk at a condensed identity level and may lock the camera static.
    """
    provider_caps = caps or cfg.video
    view = _repair_view(view, repair)
    prompt = _render_within_budget(
        view,
        image_bindings(view, plan, provider_caps),
        provider_caps.max_prompt_chars,
        retry_feedback=_merge_targets(retry_feedback, repair),
        repair=repair,
    )
    negative_prompt = ", ".join(view.style_guide.avoid)
    seed = _derive_seed(project_id, view.shot.id, attempt=attempt)
    pkg_hash = _compute_package_hash(
        view, plan, prompt, negative_prompt, seed, resolution=resolution
    )
    return Package(
        shot_id=view.shot.id,
        compiled_prompt=prompt,
        negative_prompt=negative_prompt,
        reference_asset_ids=[a.id for a in plan.selected_assets],
        reference_uris=[a.uri for a in plan.selected_assets],
        first_frame_asset_id=plan.first_frame.id if plan.first_frame else None,
        first_frame_uri=plan.first_frame.uri if plan.first_frame else None,
        duration_s=view.shot.duration_s,
        aspect_ratio=view.style_guide.aspect_ratio,
        seed=seed,
        package_hash=pkg_hash,
        resolution=resolution,
        dropped_to_verbal=list(plan.dropped_to_verbal),
    )

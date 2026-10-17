"""Deterministic Jinja2 Shot Prompt Compiler (`compile_shot`)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from .budget import RefPlan
from .config import Config, VideoProviderCfg
from .errors import PromptTooLong
from .views import ShotView

_TEMPLATE_PATH = Path(__file__).parent / "config" / "prompt_template.j2"


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
    dropped_to_verbal: list[str] = field(default_factory=list)


def _derive_seed(project_id: str, shot_id: str, attempt: int = 1) -> int:
    digest = hashlib.sha256(f"{project_id}:{shot_id}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFF_FFFF


def _render_template(
    template: jinja2.Template,
    view: ShotView,
    dropped_verbal: list[str],
    include_music: bool = True,
    truncate_descriptions: int | None = None,
) -> str:
    def _clip(text: str) -> str:
        if truncate_descriptions is not None and len(text) > truncate_descriptions:
            return text[:truncate_descriptions].rstrip() + "..."
        return text

    cast_ctx = []
    for c in view.shot.cast:
        ent = view.cast_entities.get(c.entity_id)
        app = view.cast_appearances.get(c.entity_id)
        st = view.cast_states.get(c.entity_id, {})
        holding_id = st.get("holding")
        holding_name = None
        if holding_id:
            pent = view.prop_entities.get(holding_id)
            holding_name = pent.canonical_name if pent else holding_id
        cast_ctx.append(
            {
                "entity_id": c.entity_id,
                "canonical_name": ent.canonical_name if ent else c.entity_id,
                "position": c.position,
                "framing": c.framing,
                "visual_description": _clip(app.visual_description if app else ""),
                "wardrobe": app.wardrobe if app else st.get("wearing"),
                "holding": holding_name,
                "injury": st.get("injury"),
            }
        )

    props_ctx = []
    for pid in view.shot.prop_ids:
        pent = view.prop_entities.get(pid)
        papp = view.prop_appearances.get(pid)
        props_ctx.append(
            {
                "entity_id": pid,
                "canonical_name": pent.canonical_name if pent else pid,
                "visual_description": _clip(papp.visual_description if papp else ""),
            }
        )

    dialogue_ctx = []
    for dl in view.dialogue_lines:
        sp_ent = view.cast_entities.get(dl.speaker_id)
        dialogue_ctx.append(
            {
                "speaker_name": sp_ent.canonical_name if sp_ent else dl.speaker_id,
                "delivery": dl.delivery,
                "text": dl.text,
            }
        )

    focus_name = None
    if view.shot.camera.focus_target_id:
        fid = view.shot.camera.focus_target_id
        if fid in view.cast_entities:
            focus_name = view.cast_entities[fid].canonical_name
        elif fid in view.prop_entities:
            focus_name = view.prop_entities[fid].canonical_name
        else:
            focus_name = fid

    continuity_note = None
    if view.shot.continue_from_last_frame and view.prev_shot_last_frame is not None:
        continuity_note = (
            f"Continue seamlessly from previous shot last frame ({view.prev_shot_last_frame.id}); "
            "preserve exact subject screen positions, lighting, and camera axis."
        )

    loc_app_copy = view.location_appearance.model_copy(
        update={
            "visual_description": _clip(view.location_appearance.visual_description)
        }
    )

    rendered = template.render(
        style_guide=view.style_guide,
        scene=view.scene,
        shot=view.shot,
        location=view.location,
        location_appearance=loc_app_copy,
        cast=cast_ctx,
        props=props_ctx,
        dropped_verbal=[_clip(d) for d in dropped_verbal],
        focus_name=focus_name,
        continuity_note=continuity_note,
        dialogue=dialogue_ctx,
        music=view.music_cue if include_music else None,
    )
    # Normalize blank lines
    lines = [line.rstrip() for line in rendered.splitlines() if line.strip()]
    return "\n".join(lines)


def compile_shot(
    view: ShotView,
    plan: RefPlan,
    cfg: Config,
    caps: VideoProviderCfg | None = None,
    project_id: str = "default",
    attempt: int = 1,
) -> Package:
    """Render deterministic prompt package from ShotView + RefPlan with length budget enforcement."""
    provider_caps = caps or cfg.video
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_PATH.name)

    prompt = _render_template(
        template, view, plan.dropped_to_verbal, include_music=True
    )

    # Trim low-priority sections if exceeding max_prompt_chars (never trim DIALOGUE or ACTION)
    if len(prompt) > provider_caps.max_prompt_chars:
        prompt = _render_template(
            template, view, plan.dropped_to_verbal, include_music=False
        )
    if len(prompt) > provider_caps.max_prompt_chars:
        prompt = _render_template(
            template, view, [], include_music=False, truncate_descriptions=120
        )
    if len(prompt) > provider_caps.max_prompt_chars:
        prompt = _render_template(
            template, view, [], include_music=False, truncate_descriptions=50
        )
    if len(prompt) > provider_caps.max_prompt_chars:
        raise PromptTooLong(
            f"Compiled prompt for shot '{view.shot.id}' is {len(prompt)} chars, "
            f"exceeding cap of {provider_caps.max_prompt_chars}"
        )

    negative_prompt = ", ".join(view.style_guide.avoid)
    ref_ids = [a.id for a in plan.selected_assets]
    ref_uris = [a.uri for a in plan.selected_assets]
    ref_shas = [a.sha256 for a in plan.selected_assets]
    ff_id = plan.first_frame.id if plan.first_frame else None
    ff_uri = plan.first_frame.uri if plan.first_frame else None
    ff_sha = plan.first_frame.sha256 if plan.first_frame else None
    seed = _derive_seed(project_id, view.shot.id, attempt=attempt)

    canonical_payload = json.dumps(
        {
            "shot_id": view.shot.id,
            "compiled_prompt": prompt,
            "negative_prompt": negative_prompt,
            "ref_shas": ref_shas,
            "first_frame_sha": ff_sha,
            "duration_s": view.shot.duration_s,
            "aspect_ratio": view.style_guide.aspect_ratio,
            "seed": seed,
        },
        sort_keys=True,
    )
    pkg_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()

    return Package(
        shot_id=view.shot.id,
        compiled_prompt=prompt,
        negative_prompt=negative_prompt,
        reference_asset_ids=ref_ids,
        reference_uris=ref_uris,
        first_frame_asset_id=ff_id,
        first_frame_uri=ff_uri,
        duration_s=view.shot.duration_s,
        aspect_ratio=view.style_guide.aspect_ratio,
        seed=seed,
        package_hash=pkg_hash,
        dropped_to_verbal=list(plan.dropped_to_verbal),
    )

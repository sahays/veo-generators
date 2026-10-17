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


_LANG_MAP: dict[str, str] = {
    "hi": "Hindi (hi-IN)",
    "hi-in": "Hindi (hi-IN)",
    "hindi": "Hindi (hi-IN)",
    "ta": "Tamil (ta-IN)",
    "ta-in": "Tamil (ta-IN)",
    "te": "Telugu (te-IN)",
    "te-in": "Telugu (te-IN)",
    "bn": "Bengali (bn-IN)",
    "bn-in": "Bengali (bn-IN)",
    "mr": "Marathi (mr-IN)",
    "mr-in": "Marathi (mr-IN)",
    "en": "English",
    "en-in": "English (en-IN)",
    "en-us": "English (en-US)",
}


def _clip_text(text: str, limit: int | None) -> str:
    if limit is not None and len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _build_cast_ctx(
    view: ShotView, truncate_descriptions: int | None
) -> list[dict[str, str | None]]:
    cast_ctx: list[dict[str, str | None]] = []
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
                "visual_description": _clip_text(
                    app.visual_description if app else "", truncate_descriptions
                ),
                "wardrobe": app.wardrobe if app else st.get("wearing"),
                "holding": holding_name,
                "injury": st.get("injury"),
            }
        )
    return cast_ctx


def _build_props_and_dialogue_ctx(
    view: ShotView, truncate_descriptions: int | None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    props_ctx = [
        {
            "entity_id": pid,
            "canonical_name": view.prop_entities[pid].canonical_name
            if pid in view.prop_entities
            else pid,
            "visual_description": _clip_text(
                view.prop_appearances[pid].visual_description
                if pid in view.prop_appearances
                else "",
                truncate_descriptions,
            ),
        }
        for pid in view.shot.prop_ids
    ]
    dialogue_ctx: list[dict[str, str]] = []
    for dl in view.dialogue_lines:
        sp_ent = view.cast_entities.get(dl.speaker_id)
        raw_lang = (dl.language or "en").strip()
        dialogue_ctx.append(
            {
                "speaker_name": sp_ent.canonical_name if sp_ent else dl.speaker_id,
                "delivery": dl.delivery,
                "text": dl.text,
                "language": raw_lang,
                "language_label": _LANG_MAP.get(raw_lang.lower(), raw_lang),
            }
        )
    return props_ctx, dialogue_ctx


def _resolve_focus_and_continuity(view: ShotView) -> tuple[str | None, str | None]:
    focus_name = None
    fid = view.shot.camera.focus_target_id
    if fid:
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
    return focus_name, continuity_note


def _render_template(
    template: jinja2.Template,
    view: ShotView,
    dropped_verbal: list[str],
    include_music: bool = True,
    truncate_descriptions: int | None = None,
) -> str:
    cast_ctx = _build_cast_ctx(view, truncate_descriptions)
    props_ctx, dialogue_ctx = _build_props_and_dialogue_ctx(view, truncate_descriptions)
    focus_name, continuity_note = _resolve_focus_and_continuity(view)
    loc_app_copy = view.location_appearance.model_copy(
        update={
            "visual_description": _clip_text(
                view.location_appearance.visual_description, truncate_descriptions
            )
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
        dropped_verbal=[_clip_text(d, truncate_descriptions) for d in dropped_verbal],
        focus_name=focus_name,
        continuity_note=continuity_note,
        dialogue=dialogue_ctx,
        music=view.music_cue if include_music else None,
    )
    return "\n".join(line.rstrip() for line in rendered.splitlines() if line.strip())


def _render_within_budget(
    template: jinja2.Template, view: ShotView, dropped_verbal: list[str], max_chars: int
) -> str:
    attempts: list[tuple[list[str], bool, int | None]] = [
        (dropped_verbal, True, None),
        (dropped_verbal, False, None),
        ([], False, 120),
        ([], False, 50),
    ]
    prompt = ""
    for verbal, inc_music, trunc in attempts:
        prompt = _render_template(
            template, view, verbal, include_music=inc_music, truncate_descriptions=trunc
        )
        if len(prompt) <= max_chars:
            return prompt
    raise PromptTooLong(
        f"Compiled prompt for shot '{view.shot.id}' is {len(prompt)} chars, exceeding cap of {max_chars}"
    )


def _compute_package_hash(
    view: ShotView, plan: RefPlan, prompt: str, negative_prompt: str, seed: int
) -> str:
    canonical_payload = json.dumps(
        {
            "shot_id": view.shot.id,
            "compiled_prompt": prompt,
            "negative_prompt": negative_prompt,
            "ref_shas": [a.sha256 for a in plan.selected_assets],
            "first_frame_sha": plan.first_frame.sha256 if plan.first_frame else None,
            "duration_s": view.shot.duration_s,
            "aspect_ratio": view.style_guide.aspect_ratio,
            "seed": seed,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


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
    prompt = _render_within_budget(
        template, view, plan.dropped_to_verbal, provider_caps.max_prompt_chars
    )
    negative_prompt = ", ".join(view.style_guide.avoid)
    seed = _derive_seed(project_id, view.shot.id, attempt=attempt)
    pkg_hash = _compute_package_hash(view, plan, prompt, negative_prompt, seed)
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
        dropped_to_verbal=list(plan.dropped_to_verbal),
    )

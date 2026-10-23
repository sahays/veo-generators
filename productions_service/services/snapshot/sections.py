"""Snapshot sections: entities, style guide, usage totals, legacy scene timeline, envelope."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from storygraph.config import Config
from storygraph.presets import resolve_production_presets
from storygraph.schema import Asset, Entity, EntityType, ProjectMeta, Scene, StageRun

PRESET_KEYS: tuple[str, ...] = (
    "visual_style_preset",
    "color_palette_preset",
    "director_style_preset",
    "screenplay_style_preset",
    "music_style_preset",
)
_ENTITY_GROUPS: dict[EntityType, str] = {
    EntityType.CHARACTER: "characters",
    EntityType.LOCATION: "locations",
    EntityType.OBJECT: "objects",
}
_DESIGN_KINDS: frozenset[str] = frozenset(
    {"character_sheet", "location_plate", "prop_sheet"}
)
VEO_UNIT_COST_USD = 0.15
IMAGE_UNIT_COST_USD = 0.02


def group_entities(entities: list[Entity]) -> dict[str, list[dict[str, Any]]]:
    """Serialize each entity once into characters/locations/objects (no duplicated `all`)."""
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in _ENTITY_GROUPS.values()}
    for ent in entities:
        group = _ENTITY_GROUPS.get(ent.entity_type)
        if group:
            groups[group].append(ent.model_dump(mode="json"))
    return groups


def serialize_style_guide(
    sg_raw: dict[str, Any] | None, meta: ProjectMeta
) -> dict[str, Any]:
    """StyleGuide synced with ProjectMeta presets, or one derived from the preset bundle."""
    if sg_raw is not None:
        return {
            **sg_raw,
            **{k: getattr(meta, k) for k in PRESET_KEYS if getattr(meta, k, None)},
        }
    bundle = resolve_production_presets(
        visual_style_id=meta.visual_style_preset,
        color_palette_id=meta.color_palette_preset,
        director_style_id=meta.director_style_preset,
        screenplay_style_id=meta.screenplay_style_preset,
        music_style_id=meta.music_style_preset,
    )
    vs, cp = bundle.visual_style, bundle.color_palette
    return {
        "id": "style_guide",
        "visual_medium": vs.visual_medium,
        "palette": list(cp.palette),
        "lens_language": vs.lens_language,
        "lighting_rules": f"{vs.lighting_rules} {cp.lighting_tint}".strip(),
        "aspect_ratio": meta.orientation,
        "avoid": list(vs.avoid),
        "visual_style_preset": vs.id,
        "color_palette_preset": cp.id,
        "director_style_preset": bundle.director_style.id,
        "screenplay_style_preset": bundle.screenplay_style.id,
        "music_style_preset": bundle.music_style.id,
    }


def usage_summary(
    cfg: Config,
    stage_runs: list[StageRun],
    assets: list[Asset],
    total_runs: int,
    shot_seconds: float,
) -> dict[str, Any]:
    """Cumulative token, image and Veo usage (counts over ALL runs, not just returned ones)."""
    image_count = sum(1 for a in assets if a.kind in _DESIGN_KINDS)
    veo_seconds = shot_seconds if total_runs else 0.0
    return {
        "input_tokens": sum(sr.tokens_in for sr in stage_runs),
        "output_tokens": sum(sr.tokens_out for sr in stage_runs),
        "model_name": cfg.models.story_architect,
        "cost_usd": round(sum(sr.cost_usd for sr in stage_runs), 4),
        "image_generations": image_count,
        "image_cost_usd": round(image_count * IMAGE_UNIT_COST_USD, 4),
        "veo_videos": total_runs,
        "veo_seconds": veo_seconds,
        "veo_unit_cost": VEO_UNIT_COST_USD,
        "veo_cost_usd": round(veo_seconds * VEO_UNIT_COST_USD, 4),
    }


def _mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def legacy_scenes(
    scenes: list[Scene],
    shots_out: list[dict[str, Any]],
    appearances_out: list[dict[str, Any]],
    runs_by_shot: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Backward-compatible scene timeline, built from O(1) indexes instead of nested scans."""
    shots_by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in shots_out:
        shots_by_scene[s["scene_id"]].append(s)
    thumb_by_entity: dict[str, str | None] = {
        a["entity_id"]: a["assets"][-1].get("signed_url")
        for a in appearances_out
        if a.get("assets")
    }
    out: list[dict[str, Any]] = []
    t_cursor = 0
    for sc in scenes:
        sc_shots = shots_by_scene.get(sc.id, [])
        dur = int(sum(float(s.get("duration_s", 4.0)) for s in sc_shots)) or 8
        first_run = runs_by_shot.get(sc_shots[0]["id"]) if sc_shots else None
        out.append(
            {
                "id": sc.id,
                "visual_description": sc.summary
                or f"{sc.heading} ({sc.time_of_day}, {sc.weather})",
                "narration": "",
                "music_description": sc.mood,
                "timestamp_start": _mmss(t_cursor),
                "timestamp_end": _mmss(t_cursor + dur),
                "thumbnail_url": thumb_by_entity.get(sc.location_id or ""),
                "video_url": first_run.get("output_video_signed_url")
                if first_run
                else None,
                "metadata": {"location": sc.location_id, "mood": sc.mood},
            }
        )
        t_cursor += dur
    return out


def project_envelope(
    meta: ProjectMeta, story_text: str, final_url: str | None
) -> dict[str, Any]:
    """Top-level project fields shared by the snapshot and the list summary."""
    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.type,
        "base_concept": meta.base_concept,
        "story_text": story_text or meta.base_concept,
        "video_length": meta.video_length,
        "orientation": meta.orientation,
        "language": meta.language,
        **{k: getattr(meta, k) for k in PRESET_KEYS},
        "auto_approve_gates": meta.auto_approve_gates,
        "render_quality": getattr(meta, "render_quality", "draft"),
        "video_resolution": getattr(meta, "video_resolution", "360p"),
        "status": meta.status,
        "current_stage": meta.current_stage,
        "final_video_uri": meta.final_video_uri,
        "final_video_url": final_url,
        "archived": meta.archived,
        "error_message": meta.error_message,
        "createdAt": int(meta.created_at.timestamp() * 1000),
        "updatedAt": int(meta.updated_at.timestamp() * 1000),
    }

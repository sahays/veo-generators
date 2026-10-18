"""StoryGraph snapshot serialization with signed blob URLs and legacy scene projections."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from storygraph.config import Config
from storygraph.repo import Repo
from storygraph.schema import Asset, EntityType, Scene, StageRun
from storygraph.validate import validate_all


def _group_entities(repo: Repo) -> dict[str, list[dict[str, Any]]]:
    """Serialize all Entity nodes grouped into characters, locations, objects, and all."""
    entities = repo.list_entities()
    all_out = [e.model_dump(mode="json") for e in entities]
    return {
        "characters": [
            e.model_dump(mode="json")
            for e in entities
            if e.entity_type == EntityType.CHARACTER
        ],
        "locations": [
            e.model_dump(mode="json")
            for e in entities
            if e.entity_type == EntityType.LOCATION
        ],
        "objects": [
            e.model_dump(mode="json")
            for e in entities
            if e.entity_type == EntityType.OBJECT
        ],
        "all": all_out,
    }


def _build_assets_and_appearances(
    repo: Repo, sign_fn: Callable[[str], str]
) -> tuple[list[Asset], list[dict[str, Any]], list[dict[str, Any]]]:
    """Serialize Asset and Appearance nodes with signed URLs and attached non-composite assets."""
    assets_raw = repo.list_assets()
    assets_by_id: dict[str, dict[str, Any]] = {}
    assets_out: list[dict[str, Any]] = []
    for a in assets_raw:
        ad = a.model_dump(mode="json")
        ad["signed_url"] = sign_fn(a.uri) if a.uri else None
        assets_by_id[a.id] = ad
        assets_out.append(ad)

    appearances_out: list[dict[str, Any]] = []
    for app_node in repo.list_appearances(active_only=False):
        apd = app_node.model_dump(mode="json")
        apd["assets"] = [
            assets_by_id[aid]
            for aid in app_node.asset_ids
            if aid in assets_by_id
            and assets_by_id[aid].get("kind") != "composite_sheet"
        ]
        appearances_out.append(apd)
    return assets_raw, assets_out, appearances_out


def _build_runs_and_shots(
    repo: Repo, sign_fn: Callable[[str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Serialize GenerationRun and Shot nodes, attaching `latest_run` to each shot."""
    runs_out: list[dict[str, Any]] = []
    latest_run_by_shot: dict[str, dict[str, Any]] = {}
    for r in repo.list_generation_runs():
        rd = r.model_dump(mode="json")
        if r.output_video_uri:
            rd["output_video_signed_url"] = sign_fn(r.output_video_uri)
        runs_out.append(rd)
        latest_run_by_shot[r.shot_id] = rd

    shots_out: list[dict[str, Any]] = []
    for sh in repo.list_shots():
        shd = sh.model_dump(mode="json")
        shd["latest_run"] = latest_run_by_shot.get(sh.id)
        shots_out.append(shd)
    return runs_out, shots_out


def _format_legacy_scene(
    sc: Scene,
    sc_shots: list[dict[str, Any]],
    appearances_out: list[dict[str, Any]],
    t_cursor: int,
    dur: int,
) -> dict[str, Any]:
    """Build backward-compatible scene dictionary for a single Scene node."""
    loc_apps = [
        a
        for a in appearances_out
        if a["entity_id"] == sc.location_id and a.get("assets")
    ]
    thumb_url = (
        loc_apps[-1]["assets"][-1].get("signed_url")
        if loc_apps and loc_apps[-1].get("assets")
        else None
    )
    video_url = (
        sc_shots[0]["latest_run"].get("output_video_signed_url")
        if sc_shots and sc_shots[0].get("latest_run")
        else None
    )
    return {
        "id": sc.id,
        "visual_description": sc.summary
        or f"{sc.heading} ({sc.time_of_day}, {sc.weather})",
        "narration": "",
        "music_description": sc.mood,
        "timestamp_start": f"0:{t_cursor:02d}",
        "timestamp_end": f"0:{t_cursor + dur:02d}",
        "thumbnail_url": thumb_url,
        "video_url": video_url,
        "metadata": {"location": sc.location_id, "mood": sc.mood},
    }


def _build_scenes_and_legacy(
    repo: Repo,
    shots_out: list[dict[str, Any]],
    appearances_out: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Serialize StoryGraph scenes and construct legacy scene timeline entries."""
    scenes_out: list[dict[str, Any]] = []
    legacy_scenes: list[dict[str, Any]] = []
    t_cursor = 0
    for sc in repo.list_scenes():
        scenes_out.append(sc.model_dump(mode="json"))
        sc_shots = [s for s in shots_out if s["scene_id"] == sc.id]
        dur = int(sum(float(s.get("duration_s", 4.0)) for s in sc_shots)) or 8
        legacy_scenes.append(
            _format_legacy_scene(sc, sc_shots, appearances_out, t_cursor, dur)
        )
        t_cursor += dur
    return scenes_out, legacy_scenes


def _build_usage_summary(
    repo: Repo,
    cfg: Config,
    assets_raw: list[Asset],
    runs_out: list[dict[str, Any]],
    shots_out: list[dict[str, Any]],
) -> tuple[list[StageRun], dict[str, Any]]:
    """Compute cumulative token, image, and Veo video usage metrics."""
    stage_runs = repo.list_stage_runs()
    tokens_in = sum(sr.tokens_in for sr in stage_runs)
    tokens_out = sum(sr.tokens_out for sr in stage_runs)
    cost_usd = round(sum(sr.cost_usd for sr in stage_runs), 4)
    image_count = sum(
        1
        for a in assets_raw
        if a.kind in ("character_sheet", "location_plate", "prop_sheet")
    )
    veo_videos = len(runs_out)
    veo_seconds = (
        sum(float(s.get("duration_s", 0.0)) for s in shots_out) if runs_out else 0.0
    )
    return stage_runs, {
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "model_name": cfg.models.story_architect,
        "cost_usd": cost_usd,
        "image_generations": image_count,
        "image_cost_usd": round(image_count * 0.02, 4),
        "veo_videos": veo_videos,
        "veo_seconds": veo_seconds,
        "veo_unit_cost": 0.15,
        "veo_cost_usd": round(veo_seconds * 0.15, 4),
    }


def _build_story_graph_payload(
    repo: Repo,
    cfg: Config,
    assets_out: list[dict[str, Any]],
    appearances_out: list[dict[str, Any]],
    scenes_out: list[dict[str, Any]],
    shots_out: list[dict[str, Any]],
    runs_out: list[dict[str, Any]],
    stage_runs: list[StageRun],
) -> dict[str, Any]:
    """Assemble the nested `story_graph` dictionary for the snapshot response."""
    sg = repo.get_style_guide()
    return {
        "style_guide": sg.model_dump(mode="json") if sg else None,
        "entities": _group_entities(repo),
        "events": [e.model_dump(mode="json") for e in repo.list_events()],
        "state_facts": [sf.model_dump(mode="json") for sf in repo.list_state_facts()],
        "appearances": appearances_out,
        "assets": assets_out,
        "scenes": scenes_out,
        "dialogue_lines": [d.model_dump(mode="json") for d in repo.list_dialogue()],
        "music_cues": [m.model_dump(mode="json") for m in repo.list_music_cues()],
        "shots": shots_out,
        "generation_runs": runs_out,
        "gates": [g.model_dump(mode="json") for g in repo.list_gates()],
        "stage_runs": [sr.model_dump(mode="json") for sr in stage_runs],
        "stage_qa_reports": repo.store.query("stage_qa_reports"),
        "validation_issues": [i.to_dict() for i in validate_all(repo, cfg)],
        "change_requests": [
            cr.model_dump(mode="json")
            for cr in repo.list_change_requests(open_only=False)
        ],
        "audit_log": [
            ae.model_dump(mode="json") for ae in repo.list_audit_entries(limit=150)
        ],
    }


def _build_project_envelope(
    repo: Repo,
    meta: Any,
    final_signed: str | None,
    legacy_scenes: list[dict[str, Any]],
    total_usage: dict[str, Any],
    story_graph: dict[str, Any],
) -> dict[str, Any]:
    """Assemble top-level project envelope fields around `story_graph`."""
    return {
        "id": meta.id,
        "name": meta.name,
        "type": meta.type,
        "base_concept": meta.base_concept,
        "story_text": repo.get_source_text() or meta.base_concept,
        "video_length": meta.video_length,
        "orientation": meta.orientation,
        "language": meta.language,
        "visual_style_preset": meta.visual_style_preset,
        "color_palette_preset": meta.color_palette_preset,
        "director_style_preset": meta.director_style_preset,
        "screenplay_style_preset": meta.screenplay_style_preset,
        "music_style_preset": meta.music_style_preset,
        "auto_approve_gates": meta.auto_approve_gates,
        "status": meta.status,
        "current_stage": meta.current_stage,
        "final_video_uri": meta.final_video_uri,
        "final_video_url": final_signed,
        "archived": meta.archived,
        "error_message": meta.error_message,
        "createdAt": int(meta.created_at.timestamp() * 1000),
        "updatedAt": int(meta.updated_at.timestamp() * 1000),
        "scenes": legacy_scenes,
        "total_usage": total_usage,
        "story_graph": story_graph,
    }


def format_graph_snapshot(repo: Repo, cfg: Config) -> dict[str, Any]:
    """Build a complete StoryGraph response payload with signed asset URLs and backward-compatible project fields."""
    meta = repo.get_project_meta()
    if not meta:
        raise HTTPException(
            status_code=404, detail=f"Production {repo.project_id} not found"
        )
    sign_fn: Callable[[str], str] = getattr(repo.blobs, "sign_url", lambda u: u)
    assets_raw, assets_out, appearances_out = _build_assets_and_appearances(
        repo, sign_fn
    )
    runs_out, shots_out = _build_runs_and_shots(repo, sign_fn)
    scenes_out, legacy_scenes = _build_scenes_and_legacy(
        repo, shots_out, appearances_out
    )
    stage_runs, total_usage = _build_usage_summary(
        repo, cfg, assets_raw, runs_out, shots_out
    )
    final_signed = (
        sign_fn(meta.final_video_uri) if meta.final_video_uri else meta.final_video_url
    )
    story_graph = _build_story_graph_payload(
        repo,
        cfg,
        assets_out,
        appearances_out,
        scenes_out,
        shots_out,
        runs_out,
        stage_runs,
    )
    return _build_project_envelope(
        repo, meta, final_signed, legacy_scenes, total_usage, story_graph
    )

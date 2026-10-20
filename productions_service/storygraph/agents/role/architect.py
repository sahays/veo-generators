"""STORY_ARCHITECT role agent runner (`story_architect_agent`)."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...presets import ProductionPresetBundle, resolve_production_presets
from ...schema import EntityType, Role, StateEffect
from ...story import architect_guard_block
from ...tools import write_tools as wt
from ...tools.registry import ToolContext
from ...tools.role_helpers import (
    EventDraft,
    SceneDraft,
    StoryArchitectOutput,
    extract_entities_from_story,
    normalize_entity_id,
    normalize_indian_epic_names,
    slug_id,
)
from ..runner import RoleRunResult, run_role


def _normalize_event_effects(
    effects: list[StateEffect],
    single_wardrobe: dict[str, str],
    scene_location_id: str | None = None,
) -> list[StateEffect]:
    """Canonicalize entity IDs, sub-locations, and single-wardrobe labels inside event `effects`."""
    out: list[StateEffect] = []
    for ef in effects:
        neid = normalize_entity_id(ef.entity_id)
        nval = ef.new_value
        if ef.attribute == "location" and nval:
            norm_loc = normalize_entity_id(nval) if nval.startswith("loc_") else ""
            if norm_loc and (not scene_location_id or norm_loc == scene_location_id):
                nval = norm_loc
            else:
                out.append(
                    ef.model_copy(
                        update={
                            "entity_id": neid,
                            "attribute": "sub_location",
                            "new_value": nval,
                        }
                    )
                )
                if not scene_location_id:
                    continue
                nval = scene_location_id
        elif (
            ef.attribute == "holding"
            and nval
            and nval.startswith(("loc_", "obj_", "char_"))
        ):
            nval = normalize_entity_id(nval)
        elif ef.attribute == "wearing" and neid in single_wardrobe:
            nval = "default"
        out.append(ef.model_copy(update={"entity_id": neid, "new_value": nval}))
    return out


def _resolve_active_bundle(ctx: ToolContext, story_text: str) -> ProductionPresetBundle:
    """Resolve the active `ProductionPresetBundle` from `ProjectMeta` or story text hints."""
    meta = ctx.repo.get_project_meta()
    v_id = meta.visual_style_preset if meta else None
    c_id = meta.color_palette_preset if meta else None
    d_id = meta.director_style_preset if meta else None
    if not v_id and ("chibi" in story_text.lower() or "pastel" in story_text.lower()):
        v_id = "chibi_stylized"
        c_id = c_id or "pastel_dreamy"
    return resolve_production_presets(
        visual_style_id=v_id,
        color_palette_id=c_id,
        director_style_id=d_id,
        screenplay_style_id=meta.screenplay_style_preset if meta else None,
        music_style_id=meta.music_style_preset if meta else None,
    )


def _build_story_architect_fallback(
    bundle: ProductionPresetBundle,
    aspect_ratio: str,
    scenes: list[SceneDraft],
    events: list[EventDraft],
) -> StoryArchitectOutput:
    """Build deterministic fallback StyleGuide, Scenes, and Events honoring `bundle`."""
    vs = bundle.visual_style
    cp = bundle.color_palette
    return StoryArchitectOutput(
        visual_medium=vs.visual_medium,
        palette=list(cp.palette),
        lens_language=vs.lens_language,
        lighting_rules=f"{vs.lighting_rules} {cp.lighting_tint}".strip(),
        aspect_ratio=aspect_ratio,
        avoid=list(vs.avoid),
        scenes=scenes,
        events=events,
    )


def _persist_scenes_and_events(
    ctx: ToolContext, scenes: list[SceneDraft], events: list[EventDraft]
) -> None:
    """Persist normalized Scene and Event drafts into the StoryGraph repository."""
    scene_locs: dict[str, str] = {}
    for idx, sc in enumerate(scenes, start=1):
        sid = sc.scene_id if sc.scene_id.startswith("scn_") else f"scn_{idx:03d}"
        lid = (
            normalize_entity_id(sc.location_id, EntityType.LOCATION)
            if sc.location_id.startswith("loc_")
            else slug_id(sc.location_name or sc.location_id, "loc")
        )
        scene_locs[sid] = lid
        wt.put_scene(
            ctx,
            scene_id=sid,
            index=idx,
            heading=normalize_indian_epic_names(sc.heading),
            location_id=lid,
            time_of_day=sc.time_of_day or "day",
            weather=sc.weather or "clear",
            summary=normalize_indian_epic_names(sc.summary),
            mood=sc.mood or "cinematic",
        )
    for idx, ev in enumerate(events, start=1):
        ev_id = ev.event_id if ev.event_id.startswith("evt_") else f"evt_{idx:03d}"
        wt.put_event(
            ctx,
            event_id=ev_id,
            story_order=ev.story_order or (idx * 10),
            scene_id=ev.scene_id,
            summary=normalize_indian_epic_names(ev.summary),
            participants=[normalize_entity_id(p) for p in ev.participants],
            effects=_normalize_event_effects(
                ev.effects, {}, scene_locs.get(ev.scene_id)
            ),
        )


def _persist_architect_output(
    ctx: ToolContext,
    out: StoryArchitectOutput,
    bundle: ProductionPresetBundle,
    aspect_ratio: str,
    default_scenes: list[SceneDraft],
    default_events: list[EventDraft],
) -> None:
    """Persist StyleGuide, Scenes, and Events produced by `STORY_ARCHITECT`."""
    wt.put_style_guide(
        ctx,
        visual_medium=out.visual_medium or bundle.visual_style.visual_medium,
        palette=out.palette or list(bundle.color_palette.palette),
        lens_language=out.lens_language or bundle.visual_style.lens_language,
        lighting_rules=out.lighting_rules or bundle.visual_style.lighting_rules,
        aspect_ratio=aspect_ratio or out.aspect_ratio,
        avoid=out.avoid or list(bundle.visual_style.avoid),
        visual_style_preset=bundle.visual_style.id,
        color_palette_preset=bundle.color_palette.id,
        director_style_preset=bundle.director_style.id,
        screenplay_style_preset=bundle.screenplay_style.id,
        music_style_preset=bundle.music_style.id,
    )
    _persist_scenes_and_events(
        ctx, out.scenes or default_scenes, out.events or default_events
    )


def run_story_architect(
    ctx: ToolContext,
    story_text: str,
    aspect_ratio: str = "16:9",
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run STORY_ARCHITECT (`story_architect_agent`) to expand the story idea into StyleGuide, Scenes, and Events."""
    story_text = normalize_indian_epic_names(story_text)
    _, default_scenes, default_events = extract_entities_from_story(story_text)
    bundle = _resolve_active_bundle(ctx, story_text)
    prompt = (
        f"{bundle.format_global_instruction_block()}\n\n"
        "Expand this story concept into a StyleGuide, Scene outline (as many scenes as the story naturally requires — no artificial scene or video length cap), and an unhurried chronological Event timeline.\n"
        "CRITICAL RULES:\n"
        "1. Faithfully match the active Visual Style & Color Palette presets in `visual_medium`, `palette`, `lens_language`, and `lighting_rules`.\n"
        "2. Every scene and event MUST represent the actual plot, locations, props, and characters of the user's story with zero rushing: decompose multi-stage physical actions (approach, grasp, move, place, release) into distinct sequential Event nodes, keeping every prop in one known place at a time.\n"
        "3. Use snake_case IDs (`scn_001`, `loc_<name>`, `char_<name>`, `obj_<name>`, `evt_001`).\n"
        "4. Use authentic Hindi character spellings (`Ram`, `Lakshman`, `Ravan`, `Shurpanakha`, `Sita`, `Jatayu`, `Shabari` — never 'Rama', 'Lakshmana', 'Ravana', or 'Surpanakha').\n"
        "5. Every scene must ADVANCE the story: each story moment is covered by exactly one scene; never re-stage an earlier scene's events, gags, or lines (an intentional callback must contain the word 'callback' in its summary).\n"
        "6. `time_of_day` never moves backwards between consecutive scenes in the same location (Afternoon -> Morning is invalid unless a new day is stated).\n\n"
        f"{architect_guard_block(ctx.repo)}"
        f"STORY:\n{story_text}"
    )
    res = run_role(
        role=Role.STORY_ARCHITECT,
        ctx=ctx,
        user_prompt=prompt,
        output_schema=StoryArchitectOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _build_story_architect_fallback(
            bundle, aspect_ratio, default_scenes, default_events
        ),
    )
    _persist_architect_output(
        ctx, res.output, bundle, aspect_ratio, default_scenes, default_events
    )
    return res

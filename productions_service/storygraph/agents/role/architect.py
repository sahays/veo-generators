"""STORY_ARCHITECT role agent runner (`story_architect_agent`)."""

from __future__ import annotations

from ...adapters.mock import MockLLMClient
from ...schema import EntityType, Role, StateEffect
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
    effects: list[StateEffect], single_wardrobe: dict[str, str]
) -> list[StateEffect]:
    """Canonicalize entity IDs and single-wardrobe labels inside event `effects`."""
    out: list[StateEffect] = []
    for ef in effects:
        neid = normalize_entity_id(ef.entity_id)
        nval = ef.new_value
        if (
            nval
            and ef.attribute in ("location", "holding")
            and nval.startswith(("loc_", "obj_", "char_"))
        ):
            nval = normalize_entity_id(nval)
        elif ef.attribute == "wearing" and neid in single_wardrobe:
            nval = "default"
        out.append(ef.model_copy(update={"entity_id": neid, "new_value": nval}))
    return out


def _build_story_architect_fallback(
    story_text: str,
    aspect_ratio: str,
    scenes: list[SceneDraft],
    events: list[EventDraft],
) -> StoryArchitectOutput:
    """Build deterministic fallback StyleGuide, Scenes, and Events for `story_text`."""
    is_chibi = "chibi" in story_text.lower() or "pastel" in story_text.lower()
    medium = (
        "Chibi 3D stylized animation with dreamy cotton-candy pastel colors"
        if is_chibi
        else "Anamorphic 35mm live-action cinema"
    )
    palette = (
        ["pastel pink", "cotton-candy lavender", "soft mint", "dreamy gold"]
        if is_chibi
        else ["deep teal", "warm amber", "charcoal shadow"]
    )
    lens = (
        "Soft storybook macro lens, gentle dreamy bokeh"
        if is_chibi
        else "Panavision C-Series anamorphic primes, shallow depth of field"
    )
    lighting = (
        "Warm fairy-tale golden hour glow with soft pastel ambient fill"
        if is_chibi
        else "Motivated practical tungsten key with cool atmospheric rim light"
    )
    avoid = [
        "text overlays",
        "watermarks",
        "deformed limbs",
        "dark grim horror" if is_chibi else "cartoonish rendering",
    ]
    return StoryArchitectOutput(
        visual_medium=medium,
        palette=palette,
        lens_language=lens,
        lighting_rules=lighting,
        aspect_ratio=aspect_ratio,
        avoid=avoid,
        scenes=scenes,
        events=events,
    )


def _persist_scenes_and_events(
    ctx: ToolContext, scenes: list[SceneDraft], events: list[EventDraft]
) -> None:
    """Persist normalized Scene and Event drafts into the StoryGraph repository."""
    for idx, sc in enumerate(scenes, start=1):
        sid = sc.scene_id if sc.scene_id.startswith("scn_") else f"scn_{idx:03d}"
        lid = (
            normalize_entity_id(sc.location_id, EntityType.LOCATION)
            if sc.location_id.startswith("loc_")
            else slug_id(sc.location_name or sc.location_id, "loc")
        )
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
            effects=_normalize_event_effects(ev.effects, {}),
        )


def _persist_architect_output(
    ctx: ToolContext,
    out: StoryArchitectOutput,
    aspect_ratio: str,
    default_scenes: list[SceneDraft],
    default_events: list[EventDraft],
) -> None:
    """Persist StyleGuide, Scenes, and Events produced by `STORY_ARCHITECT`."""
    wt.put_style_guide(
        ctx,
        visual_medium=out.visual_medium,
        palette=out.palette,
        lens_language=out.lens_language,
        lighting_rules=out.lighting_rules,
        aspect_ratio=aspect_ratio or out.aspect_ratio,
        avoid=out.avoid,
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
    prompt = (
        "Expand this story concept into a StyleGuide, Scene outline (2 to 4 scenes), and chronological Event timeline.\n"
        "CRITICAL RULES:\n"
        "1. Faithfully match any requested 'Visual style: ...' in `visual_medium`, `palette`, `lens_language`, and `lighting_rules`.\n"
        "2. Every scene MUST represent the actual plot, locations, and characters of the user's story.\n"
        "3. Use snake_case IDs (`scn_001`, `loc_<name>`, `char_<name>`, `obj_<name>`, `evt_001`).\n"
        "4. Use authentic Hindi character spellings (`Ram`, `Lakshman`, `Ravan`, `Shurpanakha`, `Sita`, `Jatayu`, `Shabari` — never 'Rama', 'Lakshmana', 'Ravana', or 'Surpanakha').\n\n"
        f"STORY:\n{story_text}"
    )
    res = run_role(
        role=Role.STORY_ARCHITECT,
        ctx=ctx,
        user_prompt=prompt,
        output_schema=StoryArchitectOutput,
        mock_llm=mock_llm,
        fallback_builder=lambda: _build_story_architect_fallback(
            story_text, aspect_ratio, default_scenes, default_events
        ),
    )
    _persist_architect_output(
        ctx, res.output, aspect_ratio, default_scenes, default_events
    )
    return res

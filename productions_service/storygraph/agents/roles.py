"""Role Agent runners for `STORY_ARCHITECT`, `SCRIPT_SUPERVISOR`, `SCREENWRITER`, `DIRECTOR`, and `MUSIC_DIRECTOR`."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..adapters.mock import MockLLMClient
from ..repo import Repo
from ..schema import (
    ActionBeat,
    AttributeVal,
    CameraSpec,
    CastInShot,
    EntityType,
    Provenance,
    Role,
    StateEffect,
)
from ..state import rebuild_state_facts
from ..tools import write_tools as wt
from ..tools.registry import ToolContext
from ..views import scene_view
from .runner import ROLE_AGENT_NAMES, RoleRunResult, run_role

__all__ = [
    "ROLE_AGENT_NAMES",
    "deduplicate_entities_fuzzy",
    "run_director_for_scene",
    "run_music_director",
    "run_screenwriter_for_scene",
    "run_script_supervisor",
    "run_story_architect",
]


def _slug(text: str, prefix: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return f"{prefix}_{clean or 'item'}"


# ─────────────────────────────────────────────────────────────────────────────
# Structured Output Schemas for Role Agents
# ─────────────────────────────────────────────────────────────────────────────


class SceneDraft(BaseModel):
    scene_id: str
    index: int
    heading: str
    location_id: str
    location_name: str
    time_of_day: str = "night"
    weather: str = "clear"
    summary: str
    mood: str = "cinematic"


class EventDraft(BaseModel):
    event_id: str
    story_order: int
    scene_id: str
    summary: str
    participants: list[str] = Field(default_factory=list)
    effects: list[StateEffect] = Field(default_factory=list)


class StoryArchitectOutput(BaseModel):
    visual_medium: str = "Anamorphic 35mm live-action cinema"
    palette: list[str] = Field(
        default_factory=lambda: ["deep teal", "warm amber", "charcoal shadow"]
    )
    lens_language: str = "Panavision C-Series anamorphic primes, shallow depth of field"
    lighting_rules: str = (
        "Motivated practical tungsten key with cool atmospheric rim light"
    )
    aspect_ratio: str = "16:9"
    avoid: list[str] = Field(
        default_factory=lambda: [
            "text overlays",
            "watermarks",
            "cartoonish rendering",
            "deformed limbs",
        ]
    )
    scenes: list[SceneDraft] = Field(default_factory=list)
    events: list[EventDraft] = Field(default_factory=list)


class AttributeKV(BaseModel):
    key: str
    value: str


class ExtractedEntityDraft(BaseModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: list[AttributeKV] = Field(default_factory=list)


class ScriptSupervisorOutput(BaseModel):
    entities: list[ExtractedEntityDraft] = Field(default_factory=list)
    events: list[EventDraft] = Field(default_factory=list)


class DialogueLineDraft(BaseModel):
    line_id: str
    order_in_scene: int
    speaker_id: str
    addressee_id: str | None = None
    text: str
    delivery: str = "natural"
    language: str = "en"


class ScreenwriterOutput(BaseModel):
    summary: str
    mood: str
    dialogue_lines: list[DialogueLineDraft] = Field(default_factory=list)


class ShotDraft(BaseModel):
    shot_id: str
    index_in_scene: int
    story_order: int
    covers_event_ids: list[str] = Field(default_factory=list)
    duration_s: float = 5.0
    location_id: str
    cast: list[CastInShot] = Field(default_factory=list)
    prop_ids: list[str] = Field(default_factory=list)
    camera: CameraSpec = Field(default_factory=CameraSpec)
    beats: list[ActionBeat] = Field(default_factory=list)
    dialogue_ids: list[str] = Field(default_factory=list)
    continue_from_last_frame: bool = False


class DirectorSceneOutput(BaseModel):
    shots: list[ShotDraft] = Field(default_factory=list)


class MusicCueDraft(BaseModel):
    cue_id: str
    scene_id: str
    mood: str
    instrumentation: str
    tempo_bpm: int = 92
    motif_tags: list[str] = Field(default_factory=list)


class ShotAudioDraft(BaseModel):
    shot_id: str
    music_cue_id: str | None = None
    sfx: list[str] = Field(default_factory=list)


class MusicDirectorOutput(BaseModel):
    cues: list[MusicCueDraft] = Field(default_factory=list)
    shot_audio: list[ShotAudioDraft] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic Heuristic Builders (used in offline/mock mode or fallback)
# ─────────────────────────────────────────────────────────────────────────────


def _extract_entities_from_story(
    story_text: str,
) -> tuple[
    list[ExtractedEntityDraft],
    list[SceneDraft],
    list[EventDraft],
]:
    """Parse story text / idea into rich Characters, Locations, Objects, Scenes, and Events."""
    # Strip optional "Visual style: ..." header line when scanning for proper names
    lines = [
        ln
        for ln in story_text.strip().splitlines()
        if not ln.strip().lower().startswith("visual style:")
    ]
    text = "\n".join(lines).strip() or story_text.strip()
    lower = text.lower()

    characters: list[ExtractedEntityDraft] = []
    locations: list[ExtractedEntityDraft] = []
    objects: list[ExtractedEntityDraft] = []

    known_char_patterns = [
        (
            "rama",
            "Lord Rama",
            ["Rama", "Shri Rama"],
            [AttributeKV(key="role", value="protagonist prince in forest exile")],
        ),
        (
            "sita",
            "Goddess Sita",
            ["Sita", "Janaki"],
            [AttributeKV(key="role", value="princess in forest exile")],
        ),
        (
            "lakshmana",
            "Lakshmana",
            ["Lakshman"],
            [AttributeKV(key="role", value="devoted brother and warrior")],
        ),
        (
            "ravana",
            "King Ravana",
            ["Ravana", "Demon King Ravana"],
            [AttributeKV(key="role", value="antagonist demon king of Lanka")],
        ),
        (
            "surpanakha",
            "Surpanakha",
            ["Demoness Surpanakha"],
            [AttributeKV(key="role", value="demoness sister of Ravana")],
        ),
        (
            "jatayu",
            "Jatayu",
            ["Demi-god Vulture Jatayu"],
            [AttributeKV(key="role", value="noble demi-god vulture guardian")],
        ),
        (
            "shabari",
            "Shabari",
            ["Devotee Shabari"],
            [AttributeKV(key="role", value="pious forest sage devotee")],
        ),
        (
            "arjun",
            "Arjun",
            ["Detective Arjun", "Arjun Rao"],
            [AttributeKV(key="role", value="protagonist")],
        ),
        (
            "meera",
            "Meera",
            ["Dr. Meera", "Meera Sen"],
            [AttributeKV(key="role", value="key figure")],
        ),
        ("kira", "Kira", ["Agent Kira"], [AttributeKV(key="role", value="operative")]),
        (
            "vikram",
            "Vikram",
            ["Captain Vikram"],
            [AttributeKV(key="role", value="commander")],
        ),
        ("aanya", "Aanya", ["Aanya"], [AttributeKV(key="role", value="narrator")]),
        ("rohan", "Rohan", ["Rohan"], [AttributeKV(key="role", value="lead")]),
        ("elena", "Elena", ["Elena"], [AttributeKV(key="role", value="scientist")]),
        ("maya", "Maya", ["Maya"], [AttributeKV(key="role", value="traveler")]),
    ]
    for token, cname, aliases, attrs in known_char_patterns:
        if re.search(rf"\b{token}\b", lower):
            characters.append(
                ExtractedEntityDraft(
                    entity_id=f"char_{token}",
                    entity_type=EntityType.CHARACTER,
                    canonical_name=cname,
                    aliases=aliases,
                    attributes=attrs,
                )
            )

    if not characters:
        stop_words = {
            "The",
            "In",
            "At",
            "On",
            "A",
            "An",
            "As",
            "When",
            "After",
            "Before",
            "Inside",
            "Outside",
            "Under",
            "Over",
            "Scene",
            "Int",
            "Ext",
            "Night",
            "Day",
            "Morning",
            "Evening",
            "Suddenly",
            "Later",
            "Meanwhile",
            "While",
            "Using",
            "Visual",
            "Style",
            "Chibi",
            "Book",
            "Forest",
            "Panchavati",
            "Mumbai",
            "Delhi",
            "Tokyo",
            "London",
            "Paris",
            "Station",
            "Office",
            "Cafe",
            "Lab",
            "To",
            "From",
            "With",
            "Their",
            "His",
            "Her",
        }
        found_names: list[str] = []
        for m in re.finditer(r"\b([A-Z][a-z]{2,15})\b", text):
            word = m.group(1)
            if word not in stop_words and word not in found_names:
                found_names.append(word)
            if len(found_names) >= 3:
                break
        if found_names:
            for nm in found_names:
                characters.append(
                    ExtractedEntityDraft(
                        entity_id=_slug(nm, "char"),
                        entity_type=EntityType.CHARACTER,
                        canonical_name=nm,
                        aliases=[],
                        attributes=[AttributeKV(key="role", value="character")],
                    )
                )
        else:
            characters.append(
                ExtractedEntityDraft(
                    entity_id="char_arjun",
                    entity_type=EntityType.CHARACTER,
                    canonical_name="Arjun",
                    aliases=["Protagonist"],
                    attributes=[AttributeKV(key="role", value="protagonist")],
                )
            )

    loc_keywords = [
        ("panchavati", "loc_panchavati", "Panchavati Forest Hermitage", "exterior"),
        ("forest", "loc_forest", "Enchanted Dandaka Forest", "exterior"),
        ("cafe", "loc_cafe", "Rain-Lit Corner Cafe", "interior"),
        ("station", "loc_station", "Old Railway Platform", "exterior"),
        ("office", "loc_office", "Glass High-Rise Office", "interior"),
        ("street", "loc_street", "Neon Market Street", "exterior"),
        ("alley", "loc_alley", "Rain-Slicked Back Alley", "exterior"),
        ("lab", "loc_lab", "Quantum Research Lab", "interior"),
        ("rooftop", "loc_rooftop", "Monsoon Skyline Rooftop", "exterior"),
        ("library", "loc_library", "Vaulted Archive Library", "interior"),
        ("warehouse", "loc_warehouse", "Harbor Warehouse", "interior"),
        ("beach", "loc_beach", "Misty Coastal Shore", "exterior"),
    ]
    for kw, lid, lname, env_kind in loc_keywords:
        if re.search(rf"\b{kw}\b", lower):
            locations.append(
                ExtractedEntityDraft(
                    entity_id=lid,
                    entity_type=EntityType.LOCATION,
                    canonical_name=lname,
                    aliases=[kw],
                    attributes=[AttributeKV(key="environment", value=env_kind)],
                )
            )
    if not locations:
        locations = [
            ExtractedEntityDraft(
                entity_id="loc_main_stage",
                entity_type=EntityType.LOCATION,
                canonical_name="Primary Story Setting",
                aliases=["main setting"],
                attributes=[AttributeKV(key="environment", value="interior")],
            ),
            ExtractedEntityDraft(
                entity_id="loc_exterior_plaza",
                entity_type=EntityType.LOCATION,
                canonical_name="Secondary Exterior Setting",
                aliases=["courtyard"],
                attributes=[AttributeKV(key="environment", value="exterior")],
            ),
        ]
    elif len(locations) == 1:
        locations.append(
            ExtractedEntityDraft(
                entity_id="loc_secondary_clearing",
                entity_type=EntityType.LOCATION,
                canonical_name="Deep Wilderness Clearing",
                aliases=["clearing"],
                attributes=[AttributeKV(key="environment", value="exterior")],
            )
        )

    obj_keywords = [
        (
            "golden deer",
            "obj_golden_deer",
            "Golden Deer Maricha",
            "magical golden deer",
        ),
        ("deer", "obj_golden_deer", "Golden Deer Maricha", "magical golden deer"),
        ("bow", "obj_bow", "Celestial Bow Kodanda", "sacred bow"),
        ("briefcase", "obj_briefcase", "Brushed-Steel Briefcase", "metallic case"),
        ("compass", "obj_compass", "Antique Brass Compass", "pocket instrument"),
        ("letter", "obj_letter", "Wax-Sealed Envelope", "parchment letter"),
        ("notebook", "obj_notebook", "Leather Field Journal", "worn notebook"),
        ("lantern", "obj_lantern", "Storm Brass Lantern", "oil lantern"),
        ("key", "obj_key", "Engraved Iron Key", "ornate key"),
        ("phone", "obj_phone", "Cracked Matte Smartphone", "handheld device"),
        ("watch", "obj_watch", "Silver Chronograph Watch", "wristwatch"),
        ("umbrella", "obj_umbrella", "Black Canopy Umbrella", "rain umbrella"),
        ("cup", "obj_cup", "Porcelain Espresso Cup", "ceramic cup"),
    ]
    for kw, oid, oname, odesc in obj_keywords:
        if re.search(rf"\b{kw}\b", lower) and not any(
            o.entity_id == oid for o in objects
        ):
            objects.append(
                ExtractedEntityDraft(
                    entity_id=oid,
                    entity_type=EntityType.OBJECT,
                    canonical_name=oname,
                    aliases=[kw],
                    attributes=[AttributeKV(key="type", value=odesc)],
                )
            )
    if not objects:
        objects.append(
            ExtractedEntityDraft(
                entity_id="obj_relic",
                entity_type=EntityType.OBJECT,
                canonical_name="Sacred Story Talisman",
                aliases=["talisman"],
                attributes=[AttributeKV(key="type", value="hero prop")],
            )
        )

    wardrobe_1 = "trenchcoat" if "trenchcoat" in lower or "coat" in lower else "default"
    wardrobe_2 = (
        "formal_suit"
        if "suit" in lower or "tuxedo" in lower
        else ("rain_soaked" if "rain" in lower or "storm" in lower else wardrobe_1)
    )

    weather_val = "rain" if "rain" in lower or "monsoon" in lower else "clear"
    lead_char = characters[0]
    loc_1 = locations[0]
    loc_2 = locations[1] if len(locations) > 1 else locations[0]
    hero_obj = objects[0]

    participants_1 = [c.entity_id for c in characters]
    participants_2 = [c.entity_id for c in characters]

    scenes = [
        SceneDraft(
            scene_id="scn_001",
            index=1,
            heading=f"EXT. {loc_1.canonical_name.upper()} - DAY",
            location_id=loc_1.entity_id,
            location_name=loc_1.canonical_name,
            time_of_day="day",
            weather=weather_val,
            summary=f"{lead_char.canonical_name} and companions encounter the opening conflict around {hero_obj.canonical_name} at {loc_1.canonical_name}.",
            mood="dramatic, atmospheric",
        ),
        SceneDraft(
            scene_id="scn_002",
            index=2,
            heading=f"EXT. {loc_2.canonical_name.upper()} - DUSK",
            location_id=loc_2.entity_id,
            location_name=loc_2.canonical_name,
            time_of_day="dusk",
            weather=weather_val,
            summary=f"{lead_char.canonical_name} pursues the quest across {loc_2.canonical_name} with {hero_obj.canonical_name}.",
            mood="urgent, cinematic",
        ),
    ]

    effects_ev1 = [
        StateEffect(
            entity_id=lead_char.entity_id,
            attribute="location",
            new_value=loc_1.entity_id,
        ),
        StateEffect(
            entity_id=lead_char.entity_id,
            attribute="wearing",
            new_value=wardrobe_1,
        ),
        StateEffect(
            entity_id=lead_char.entity_id,
            attribute="holding",
            new_value=hero_obj.entity_id,
        ),
        StateEffect(
            entity_id=hero_obj.entity_id,
            attribute="location",
            new_value=loc_1.entity_id,
        ),
    ]
    for extra_c in characters[1:]:
        effects_ev1.extend(
            [
                StateEffect(
                    entity_id=extra_c.entity_id,
                    attribute="location",
                    new_value=loc_1.entity_id,
                ),
                StateEffect(
                    entity_id=extra_c.entity_id,
                    attribute="wearing",
                    new_value="default",
                ),
            ]
        )

    effects_ev2 = [
        StateEffect(
            entity_id=lead_char.entity_id,
            attribute="location",
            new_value=loc_2.entity_id,
        ),
        StateEffect(
            entity_id=lead_char.entity_id,
            attribute="wearing",
            new_value=wardrobe_2,
        ),
        StateEffect(
            entity_id=hero_obj.entity_id,
            attribute="location",
            new_value=loc_2.entity_id,
        ),
    ]
    for extra_c in characters[1:]:
        effects_ev2.append(
            StateEffect(
                entity_id=extra_c.entity_id,
                attribute="location",
                new_value=loc_2.entity_id,
            )
        )

    events = [
        EventDraft(
            event_id="evt_001",
            story_order=10,
            scene_id="scn_001",
            summary=scenes[0].summary,
            participants=participants_1,
            effects=effects_ev1,
        ),
        EventDraft(
            event_id="evt_002",
            story_order=20,
            scene_id="scn_002",
            summary=scenes[1].summary,
            participants=participants_2,
            effects=effects_ev2,
        ),
    ]
    all_entities = [*characters, *locations, *objects]
    return all_entities, scenes, events


# ─────────────────────────────────────────────────────────────────────────────
# Stage S1 — STORY_ARCHITECT + SCRIPT_SUPERVISOR + Fuzzy Deduplication
# ─────────────────────────────────────────────────────────────────────────────


def deduplicate_entities_fuzzy(repo: Repo, threshold: float = 88.0) -> list[str]:
    """Deterministically merge duplicate Entities within the same EntityType using rapidfuzz."""
    merged_drop_ids: list[str] = []
    ctx = ToolContext(repo=repo, role=Role.SCRIPT_SUPERVISOR, cfg=None)  # type: ignore[arg-type]

    for et in (EntityType.CHARACTER, EntityType.LOCATION, EntityType.OBJECT):
        entities = repo.list_entities(entity_type=et)
        kept: list = []
        for cand in entities:
            cand_names = [cand.canonical_name, *cand.aliases]
            matched_keep = None
            for existing in kept:
                ex_names = [existing.canonical_name, *existing.aliases]
                best_ratio = max(
                    (
                        fuzz.ratio(a.strip().lower(), b.strip().lower())
                        for a in cand_names
                        for b in ex_names
                        if a.strip() and b.strip()
                    ),
                    default=0.0,
                )
                if best_ratio >= threshold:
                    matched_keep = existing
                    break
            if matched_keep is not None:
                wt.propose_entity_merge(
                    ctx,
                    keep_id=matched_keep.id,
                    drop_id=cand.id,
                    reason=f"Fuzzy alias match >= {threshold}",
                )
                merged_drop_ids.append(cand.id)
            else:
                kept.append(cand)
    return merged_drop_ids


def run_story_architect(
    ctx: ToolContext,
    story_text: str,
    aspect_ratio: str = "16:9",
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run STORY_ARCHITECT (`story_architect_agent`) to expand the story idea into StyleGuide, Scenes, and Events."""
    _, default_scenes, default_events = _extract_entities_from_story(story_text)

    def _fallback() -> StoryArchitectOutput:
        is_chibi = "chibi" in story_text.lower() or "pastel" in story_text.lower()
        return StoryArchitectOutput(
            visual_medium=(
                "Chibi 3D stylized animation with dreamy cotton-candy pastel colors"
                if is_chibi
                else "Anamorphic 35mm live-action cinema"
            ),
            palette=(
                ["pastel pink", "cotton-candy lavender", "soft mint", "dreamy gold"]
                if is_chibi
                else ["deep teal", "warm amber", "charcoal shadow"]
            ),
            lens_language=(
                "Soft storybook macro lens, gentle dreamy bokeh"
                if is_chibi
                else "Panavision C-Series anamorphic primes, shallow depth of field"
            ),
            lighting_rules=(
                "Warm fairy-tale golden hour glow with soft pastel ambient fill"
                if is_chibi
                else "Motivated practical tungsten key with cool atmospheric rim light"
            ),
            aspect_ratio=aspect_ratio,
            avoid=(
                ["text overlays", "watermarks", "deformed limbs", "dark grim horror"]
                if is_chibi
                else [
                    "text overlays",
                    "watermarks",
                    "cartoonish rendering",
                    "deformed limbs",
                ]
            ),
            scenes=default_scenes,
            events=default_events,
        )

    res = run_role(
        role=Role.STORY_ARCHITECT,
        ctx=ctx,
        user_prompt=(
            "Expand this story concept into a StyleGuide, Scene outline (2 to 4 scenes), and chronological Event timeline.\n"
            "CRITICAL RULES:\n"
            "1. If the input specifies a 'Visual style: ...' (such as Chibi, pastel, anime, watercolor, etc.), "
            "you MUST set `visual_medium`, `palette`, `lens_language`, and `lighting_rules` to faithfully match that exact visual style, "
            "and do NOT put 'cartoonish rendering' in `avoid` if the style is animated/chibi!\n"
            "2. Every scene MUST represent the actual plot, locations, and characters of the user's story.\n"
            "3. Use snake_case IDs: `scn_001`, `scn_002` for scenes; `loc_<name>` for location_id; `char_<name>` for character IDs; "
            "`obj_<name>` for objects; `evt_001`, `evt_002` (with `story_order` 10, 20, 30...) for events.\n\n"
            f"STORY:\n{story_text}"
        ),
        output_schema=StoryArchitectOutput,
        mock_llm=mock_llm,
        fallback_builder=_fallback,
    )
    out: StoryArchitectOutput = res.output

    wt.put_style_guide(
        ctx,
        visual_medium=out.visual_medium,
        palette=out.palette,
        lens_language=out.lens_language,
        lighting_rules=out.lighting_rules,
        aspect_ratio=aspect_ratio or out.aspect_ratio,
        avoid=out.avoid,
    )
    scenes_to_write = out.scenes or default_scenes
    for idx, sc in enumerate(scenes_to_write, start=1):
        sid = sc.scene_id if sc.scene_id.startswith("scn_") else f"scn_{idx:03d}"
        lid = (
            sc.location_id
            if sc.location_id.startswith("loc_")
            else _slug(sc.location_name or sc.location_id, "loc")
        )
        wt.put_scene(
            ctx,
            scene_id=sid,
            index=idx,
            heading=sc.heading,
            location_id=lid,
            time_of_day=sc.time_of_day or "day",
            weather=sc.weather or "clear",
            summary=sc.summary,
            mood=sc.mood or "cinematic",
        )
    for idx, ev in enumerate(out.events or default_events, start=1):
        wt.put_event(
            ctx,
            event_id=ev.event_id
            if ev.event_id.startswith("evt_")
            else f"evt_{idx:03d}",
            story_order=ev.story_order or (idx * 10),
            scene_id=ev.scene_id,
            summary=ev.summary,
            participants=ev.participants,
            effects=ev.effects,
        )
    return res


def run_script_supervisor(
    ctx: ToolContext,
    story_text: str,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    """Run SCRIPT_SUPERVISOR (`script_supervisor_agent`) to canonicalize Characters, Locations, Objects, and StateEffects."""
    default_entities, _, default_events = _extract_entities_from_story(story_text)
    existing_scenes = ctx.repo.list_scenes()
    scenes_context = [
        {
            "scene_id": s.id,
            "location_id": s.location_id,
            "heading": s.heading,
            "summary": s.summary,
        }
        for s in existing_scenes
    ]

    def _fallback() -> ScriptSupervisorOutput:
        return ScriptSupervisorOutput(
            entities=default_entities,
            events=default_events,
        )

    res = run_role(
        role=Role.SCRIPT_SUPERVISOR,
        ctx=ctx,
        user_prompt=(
            "Extract all canonical Entities (`character`, `location`, `object`) and chronological Event state transitions from this story.\n"
            "CRITICAL RULES:\n"
            f"1. Existing scenes from STORY_ARCHITECT: {scenes_context}\n"
            "2. Create a `location` entity for EVERY `location_id` used in the scenes above.\n"
            "3. Create `character` entities (`char_<name>`) for all key characters in the story (e.g. Rama, Sita, Lakshmana, Surpanakha, Ravana, Jatayu, Shabari, etc.).\n"
            "4. Create `object` entities (`obj_<name>`) for key story props/creatures/items (e.g. Golden Deer Maricha, Rama's Bow, etc.).\n"
            "5. Create `events` (`evt_001`, `evt_002`, ...) matching each `scene_id` with `story_order` (10, 20, 30...) and `effects` setting each participant's `location` to the scene's `location_id` and `wearing` to their attire state.\n\n"
            f"STORY:\n{story_text}"
        ),
        output_schema=ScriptSupervisorOutput,
        mock_llm=mock_llm,
        fallback_builder=_fallback,
    )
    out: ScriptSupervisorOutput = res.output

    for ent in out.entities or default_entities:
        eid = ent.entity_id
        if ent.entity_type == EntityType.CHARACTER and not eid.startswith("char_"):
            eid = _slug(ent.canonical_name or eid, "char")
        elif ent.entity_type == EntityType.LOCATION and not eid.startswith("loc_"):
            eid = _slug(ent.canonical_name or eid, "loc")
        elif ent.entity_type == EntityType.OBJECT and not eid.startswith("obj_"):
            eid = _slug(ent.canonical_name or eid, "obj")

        attr_map = {
            kv.key: AttributeVal(
                value=kv.value,
                provenance=Provenance.FROM_TEXT,
                source_span=(0, min(len(story_text), 64)),
            )
            for kv in ent.attributes
            if kv.key
        }
        wt.put_entity(
            ctx,
            entity_id=eid,
            entity_type=ent.entity_type,
            canonical_name=ent.canonical_name,
            aliases=ent.aliases,
            attributes=attr_map,
        )

    for ev in out.events:
        wt.put_event(
            ctx,
            event_id=ev.event_id,
            story_order=ev.story_order,
            scene_id=ev.scene_id,
            summary=ev.summary,
            participants=ev.participants,
            effects=ev.effects,
        )

    deduplicate_entities_fuzzy(ctx.repo)

    # Guarantee every scene location_id has a matching LOCATION entity in repo
    for sc in ctx.repo.list_scenes():
        if not ctx.repo.get_entity(sc.location_id):
            loc_title = sc.location_id.replace("loc_", "").replace("_", " ").title()
            wt.put_entity(
                ctx,
                entity_id=sc.location_id,
                entity_type=EntityType.LOCATION,
                canonical_name=loc_title,
                aliases=[],
                attributes={
                    "heading": AttributeVal(
                        value=sc.heading, provenance=Provenance.FROM_TEXT
                    )
                },
            )

    # Guarantee at least one CHARACTER and one OBJECT exist
    if not ctx.repo.list_entities(entity_type=EntityType.CHARACTER):
        for de in default_entities:
            if de.entity_type == EntityType.CHARACTER:
                wt.put_entity(
                    ctx,
                    entity_id=de.entity_id,
                    entity_type=EntityType.CHARACTER,
                    canonical_name=de.canonical_name,
                    aliases=de.aliases,
                )
    if not ctx.repo.list_entities(entity_type=EntityType.OBJECT):
        for de in default_entities:
            if de.entity_type == EntityType.OBJECT:
                wt.put_entity(
                    ctx,
                    entity_id=de.entity_id,
                    entity_type=EntityType.OBJECT,
                    canonical_name=de.canonical_name,
                    aliases=de.aliases,
                )

    # Ensure every scene has a canonical Event that places all characters and props at scene.location_id
    # (preserving any custom wearing/holding effects when explicitly running single-scene multi-event stories)
    all_chars = ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    all_objs = ctx.repo.list_entities(entity_type=EntityType.OBJECT)
    existing_events = ctx.repo.list_events()
    scenes_list = ctx.repo.list_scenes()

    if scenes_list:
        for idx, sc in enumerate(scenes_list, start=1):
            sc_events = [e for e in existing_events if e.scene_id == sc.id]
            base_order = idx * 10
            if not sc_events:
                ev_id = f"evt_{sc.id}"
                participants = [c.id for c in all_chars]
                effects: list[StateEffect] = []
                for c in all_chars:
                    effects.append(
                        StateEffect(
                            entity_id=c.id,
                            attribute="location",
                            new_value=sc.location_id,
                        )
                    )
                    effects.append(
                        StateEffect(
                            entity_id=c.id, attribute="wearing", new_value="default"
                        )
                    )
                for o in all_objs:
                    effects.append(
                        StateEffect(
                            entity_id=o.id,
                            attribute="location",
                            new_value=sc.location_id,
                        )
                    )
                wt.put_event(
                    ctx,
                    event_id=ev_id,
                    story_order=base_order,
                    scene_id=sc.id,
                    summary=sc.summary or sc.heading,
                    participants=participants,
                    effects=effects,
                )
            else:
                # Enrich the first event of the scene so every character/object is present at sc.location_id
                first_ev = sc_events[0]
                existing_pairs = {
                    (ef.entity_id, ef.attribute) for ef in first_ev.effects
                }
                new_effects = list(first_ev.effects)
                valid_char_ids = {c.id for c in all_chars}
                participants = [
                    p for p in first_ev.participants if p in valid_char_ids
                ] or [c.id for c in all_chars]
                for c in all_chars:
                    if (c.id, "location") not in existing_pairs:
                        new_effects.append(
                            StateEffect(
                                entity_id=c.id,
                                attribute="location",
                                new_value=sc.location_id,
                            )
                        )
                    if (c.id, "wearing") not in existing_pairs:
                        new_effects.append(
                            StateEffect(
                                entity_id=c.id,
                                attribute="wearing",
                                new_value="default",
                            )
                        )
                for o in all_objs:
                    if (o.id, "location") not in existing_pairs:
                        new_effects.append(
                            StateEffect(
                                entity_id=o.id,
                                attribute="location",
                                new_value=sc.location_id,
                            )
                        )
                wt.put_event(
                    ctx,
                    event_id=first_ev.id,
                    story_order=first_ev.story_order or base_order,
                    scene_id=sc.id,
                    summary=first_ev.summary or sc.summary or sc.heading,
                    participants=participants,
                    effects=new_effects,
                )

    rebuild_state_facts(ctx.repo)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Stage S2 — SCREENWRITER (Per-Scene Screenplay & Dialogue)
# ─────────────────────────────────────────────────────────────────────────────


def run_screenwriter_for_scene(
    ctx: ToolContext,
    scene_id: str,
    language: str = "en",
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    sview = scene_view(ctx.repo, scene_id)
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ]
    if not chars:
        chars = ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    lead_id = chars[0].id if chars else "char_arjun"
    lead_name = chars[0].canonical_name if chars else "Arjun"
    valid_char_ids = {c.id for c in chars}
    story_context = ctx.repo.get_source_text() or ""

    def _fallback() -> ScreenwriterOutput:
        line_id = f"dlg_{scene_id}_01"
        return ScreenwriterOutput(
            summary=sview.scene.summary
            or f"{lead_name} confronts the pivotal turning point in {sview.scene.heading}.",
            mood=sview.scene.mood or "tense, cinematic",
            dialogue_lines=[
                DialogueLineDraft(
                    line_id=line_id,
                    order_in_scene=1,
                    speaker_id=lead_id,
                    text="Every detail leads back to this moment.",
                    delivery="low, measured intensity",
                    language=language.split("-")[0] if language else "en",
                )
            ],
        )

    res = run_role(
        role=Role.SCREENWRITER,
        ctx=ctx,
        user_prompt=(
            f"Full Story Context:\n{story_context}\n\n"
            f"Valid character speaker_ids in this scene: {[{'id': c.id, 'name': c.canonical_name} for c in chars]}\n"
            f"Write dramatic beat summary, mood, and 1 to 2 concise spoken dialogue lines (max 10 words per line) "
            f"for scene {scene_id}:\n{sview.model_dump_json()}"
        ),
        output_schema=ScreenwriterOutput,
        mock_llm=mock_llm,
        fallback_builder=_fallback,
    )
    out: ScreenwriterOutput = res.output
    wt.update_scene_script(ctx, scene_id=scene_id, summary=out.summary, mood=out.mood)
    for idx, dl in enumerate(out.dialogue_lines, start=1):
        sp_id = dl.speaker_id if dl.speaker_id in valid_char_ids else lead_id
        words = dl.text.split()
        capped_text = " ".join(words[:11]) if len(words) > 11 else dl.text
        wt.put_dialogue(
            ctx,
            line_id=f"dlg_{scene_id}_{idx:02d}",
            scene_id=scene_id,
            order_in_scene=idx,
            speaker_id=sp_id,
            addressee_id=dl.addressee_id if dl.addressee_id in valid_char_ids else None,
            text=capped_text,
            delivery=dl.delivery or "natural",
            language=dl.language or (language.split("-")[0] if language else "en"),
        )
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Stage S4 — DIRECTOR (Per-Scene Shot Breakdown)
# ─────────────────────────────────────────────────────────────────────────────


def run_director_for_scene(
    ctx: ToolContext,
    scene_id: str,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    sview = scene_view(ctx.repo, scene_id)
    chars = [
        e for e in sview.entities_in_scene if e.entity_type == EntityType.CHARACTER
    ]
    if not chars:
        chars = ctx.repo.list_entities(entity_type=EntityType.CHARACTER)
    props = [e for e in sview.entities_in_scene if e.entity_type == EntityType.OBJECT]
    if not props:
        props = ctx.repo.list_entities(entity_type=EntityType.OBJECT)

    events = sview.events
    base_order = events[0].story_order if events else (sview.scene.index * 10)
    ev_ids = [e.id for e in events]
    dlg_lines = sview.dialogue_lines
    dlg_ids = [d.id for d in dlg_lines]
    dlg_by_id = {d.id: d for d in dlg_lines}
    lead_id = chars[0].id if chars else "char_arjun"
    lead_name = chars[0].canonical_name if chars else "Arjun"
    valid_char_ids = {c.id for c in chars}
    valid_prop_ids = {p.id for p in props}
    prop_id_list = [p.id for p in props[:1]]
    story_context = ctx.repo.get_source_text() or ""

    def _fallback() -> DirectorSceneOutput:
        shot_1_id = f"shot_{scene_id}_01"
        shot_2_id = f"shot_{scene_id}_02"
        cast_list = [
            CastInShot(
                entity_id=lead_id,
                position="center",
                framing="MCU",
                speaking=bool(dlg_ids),
            )
        ]
        for extra_c in chars[1:2]:
            cast_list.append(
                CastInShot(
                    entity_id=extra_c.id,
                    position="right",
                    framing="MS",
                    speaking=False,
                )
            )
        return DirectorSceneOutput(
            shots=[
                ShotDraft(
                    shot_id=shot_1_id,
                    index_in_scene=1,
                    story_order=base_order,
                    covers_event_ids=ev_ids,
                    duration_s=5.0,
                    location_id=sview.scene.location_id,
                    cast=cast_list,
                    prop_ids=prop_id_list,
                    camera=CameraSpec(
                        shot_size="WS" if sview.scene.index == 1 else "MCU",
                        angle="eye",
                        movement="dolly_in",
                        lens_mm=35,
                        focus_target_id=lead_id,
                    ),
                    beats=[
                        ActionBeat(
                            t_start_s=0.0,
                            t_end_s=2.5,
                            description=f"{lead_name} enters {sview.location.canonical_name}: {sview.scene.summary}",
                            subject_ids=[lead_id],
                        ),
                        ActionBeat(
                            t_start_s=2.5,
                            t_end_s=5.0,
                            description=f"{lead_name} reacts to the unfolding events in {sview.location.canonical_name}.",
                            subject_ids=[lead_id, *prop_id_list],
                        ),
                    ],
                    dialogue_ids=dlg_ids[:1],
                    continue_from_last_frame=False,
                ),
                ShotDraft(
                    shot_id=shot_2_id,
                    index_in_scene=2,
                    story_order=base_order + 1,
                    covers_event_ids=ev_ids,
                    duration_s=5.0,
                    location_id=sview.scene.location_id,
                    cast=[
                        CastInShot(
                            entity_id=lead_id,
                            position="center",
                            framing="CU",
                            speaking=len(dlg_ids) > 1,
                        )
                    ],
                    prop_ids=prop_id_list,
                    camera=CameraSpec(
                        shot_size="CU",
                        angle="low",
                        movement="static",
                        lens_mm=50,
                        focus_target_id=prop_id_list[0] if prop_id_list else lead_id,
                    ),
                    beats=[
                        ActionBeat(
                            t_start_s=0.0,
                            t_end_s=5.0,
                            description=f"Dramatic close-up in {sview.location.canonical_name} as the scene reaches its climax.",
                            subject_ids=[lead_id, *prop_id_list],
                        )
                    ],
                    dialogue_ids=dlg_ids[1:],
                    continue_from_last_frame=True,
                ),
            ]
        )

    res = run_role(
        role=Role.DIRECTOR,
        ctx=ctx,
        user_prompt=(
            f"Full Story Context:\n{story_context}\n\n"
            f"Break scene '{scene_id}' (location_id='{sview.scene.location_id}') into 2 cinematic Shot nodes.\n"
            f"Valid character entity_ids: {[{'id': c.id, 'name': c.canonical_name} for c in chars]}\n"
            f"Valid prop_ids: {[{'id': p.id, 'name': p.canonical_name} for p in props]}\n"
            f"Valid event_ids to cover: {ev_ids}\n"
            f"Valid dialogue_ids: {[{'id': d.id, 'speaker_id': d.speaker_id, 'text': d.text} for d in dlg_lines]}\n"
            "Make every ActionBeat description vividly depict the exact story action happening in this scene!\n\n"
            f"SCENE VIEW:\n{sview.model_dump_json()}"
        ),
        output_schema=DirectorSceneOutput,
        mock_llm=mock_llm,
        fallback_builder=_fallback,
    )
    out: DirectorSceneOutput = res.output
    shots_to_write = out.shots or _fallback().shots

    for idx, sh in enumerate(shots_to_write, start=1):
        shot_id = f"shot_{scene_id}_{idx:02d}"
        dur = max(4.0, min(float(sh.duration_s or 5.0), 8.0))
        shot_dlgs = [did for did in sh.dialogue_ids if did in dlg_by_id]
        if idx == 1 and not shot_dlgs and dlg_ids:
            shot_dlgs = dlg_ids[:1]

        # Ensure duration accommodates spoken words (V8: <= 2.8 words/sec)
        total_words = sum(len(dlg_by_id[did].text.split()) for did in shot_dlgs)
        if total_words > 0:
            min_dur_for_speech = round((total_words / 2.5) + 0.5, 1)
            dur = max(dur, min(8.0, min_dur_for_speech))

        # Normalize cast so all valid characters and any dialogue speakers are included (V3, V9)
        # Clear appearance_id so repo.put_shot deterministically resolves appearance_for(entity_id, story_order) (V1, V2)
        cast_by_id: dict[str, CastInShot] = {}
        for c in sh.cast:
            if c.entity_id in valid_char_ids:
                cast_by_id[c.entity_id] = c.model_copy(update={"appearance_id": ""})

        if not cast_by_id:
            cast_by_id[lead_id] = CastInShot(
                entity_id=lead_id,
                position="center",
                framing="MCU",
                speaking=bool(shot_dlgs),
            )
        for did in shot_dlgs:
            sp_id = dlg_by_id[did].speaker_id
            if sp_id in valid_char_ids:
                if sp_id in cast_by_id:
                    cast_by_id[sp_id] = cast_by_id[sp_id].model_copy(
                        update={"speaking": True}
                    )
                else:
                    cast_by_id[sp_id] = CastInShot(
                        entity_id=sp_id, position="center", framing="MCU", speaking=True
                    )

        clean_props = [
            pid for pid in sh.prop_ids if pid in valid_prop_ids
        ] or prop_id_list

        # Normalize beats so they are non-overlapping within [0.0, dur] (V7)
        raw_beats = sh.beats or [
            ActionBeat(
                t_start_s=0.0,
                t_end_s=dur,
                description=sview.scene.summary or f"Action in {sview.scene.heading}",
                subject_ids=list(cast_by_id.keys()),
            )
        ]
        step = round(dur / max(1, len(raw_beats)), 2)
        clean_beats: list[ActionBeat] = []
        for b_idx, b in enumerate(raw_beats):
            t0 = round(b_idx * step, 2)
            t1 = round(dur if b_idx == len(raw_beats) - 1 else (b_idx + 1) * step, 2)
            subj = [
                sid
                for sid in b.subject_ids
                if sid in valid_char_ids or sid in valid_prop_ids
            ] or list(cast_by_id.keys())
            clean_beats.append(
                ActionBeat(
                    t_start_s=t0,
                    t_end_s=max(t0 + 0.5, t1),
                    description=b.description,
                    subject_ids=subj,
                )
            )

        wt.put_shot(
            ctx,
            shot_id=shot_id,
            scene_id=scene_id,
            index_in_scene=idx,
            story_order=base_order + (idx - 1),
            duration_s=dur,
            location_id=sview.scene.location_id,
            covers_event_ids=ev_ids,
            cast=list(cast_by_id.values()),
            prop_ids=clean_props,
            camera=sh.camera,
            beats=clean_beats,
            dialogue_ids=shot_dlgs,
            continue_from_last_frame=(idx > 1),
        )
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Stage S5 — MUSIC_DIRECTOR (Scene MusicCues & Shot SFX)
# ─────────────────────────────────────────────────────────────────────────────


def run_music_director(
    ctx: ToolContext,
    mock_llm: MockLLMClient | None = None,
) -> RoleRunResult:
    scenes = ctx.repo.list_scenes()
    shots = ctx.repo.list_shots()
    story_context = ctx.repo.get_source_text() or ""

    def _fallback() -> MusicDirectorOutput:
        cues: list[MusicCueDraft] = []
        shot_audio: list[ShotAudioDraft] = []
        for sc in scenes:
            cid = f"cue_{sc.id}"
            cues.append(
                MusicCueDraft(
                    cue_id=cid,
                    scene_id=sc.id,
                    mood=sc.mood or "dramatic atmospheric",
                    instrumentation="expressive orchestral strings, bansuri flute, gentle percussion",
                    tempo_bpm=88 if sc.index == 1 else 104,
                    motif_tags=["main_theme", sc.time_of_day],
                )
            )
        for sh in shots:
            cid = f"cue_{sh.scene_id}"
            sfx_list = ["ambient nature atmosphere", "gentle wind rustling"]
            shot_audio.append(
                ShotAudioDraft(
                    shot_id=sh.id,
                    music_cue_id=cid,
                    sfx=sfx_list,
                )
            )
        return MusicDirectorOutput(cues=cues, shot_audio=shot_audio)

    res = run_role(
        role=Role.MUSIC_DIRECTOR,
        ctx=ctx,
        user_prompt=(
            f"Story Context:\n{story_context}\n\n"
            f"Scenes: {[{'id': s.id, 'heading': s.heading, 'mood': s.mood} for s in scenes]}\n"
            f"Shots: {[{'id': sh.id, 'scene_id': sh.scene_id} for sh in shots]}\n"
            "Design scene MusicCues and per-shot SFX matching the cultural, emotional, and visual world of this story."
        ),
        output_schema=MusicDirectorOutput,
        mock_llm=mock_llm,
        fallback_builder=_fallback,
    )
    out: MusicDirectorOutput = res.output
    for cue in out.cues or _fallback().cues:
        wt.put_music_cue(
            ctx,
            cue_id=cue.cue_id,
            scene_id=cue.scene_id,
            mood=cue.mood,
            instrumentation=cue.instrumentation,
            tempo_bpm=cue.tempo_bpm,
            motif_tags=cue.motif_tags,
        )
    for sa in out.shot_audio or _fallback().shot_audio:
        if ctx.repo.get_shot(sa.shot_id):
            wt.set_shot_audio(
                ctx,
                shot_id=sa.shot_id,
                music_cue_id=sa.music_cue_id,
                sfx=sa.sfx,
            )
    return res

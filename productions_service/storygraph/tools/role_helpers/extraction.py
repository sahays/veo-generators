"""Heuristic story text entity, scene, and event extractors for Role Agents."""

from __future__ import annotations

import re

from ...schema import EntityType, StateEffect
from .models import AttributeKV, EventDraft, ExtractedEntityDraft, SceneDraft
from .normalization import normalize_indian_epic_names, slug_id

_KNOWN_CHAR_PATTERNS = [
    ("ram", "Lord Ram", ["Ram", "Shri Ram"], "protagonist prince in forest exile"),
    ("sita", "Mata Sita", ["Sita", "Janaki"], "princess in forest exile"),
    ("lakshman", "Lakshman", ["Prince Lakshman"], "devoted brother and warrior"),
    ("ravan", "Ravan", ["King Ravan"], "antagonist demon king of Lanka"),
    (
        "shurpanakha",
        "Shurpanakha",
        ["Demoness Shurpanakha"],
        "demoness sister of Ravan",
    ),
    ("jatayu", "Jatayu", ["Vulture King Jatayu"], "noble demi-god vulture guardian"),
    ("shabari", "Shabari", ["Devotee Shabari"], "pious forest sage devotee"),
    ("arjun", "Arjun", ["Detective Arjun", "Arjun Rao"], "protagonist"),
    ("meera", "Meera", ["Dr. Meera", "Meera Sen"], "key figure"),
    ("kira", "Kira", ["Agent Kira"], "operative"),
    ("vikram", "Vikram", ["Captain Vikram"], "commander"),
    ("aanya", "Aanya", ["Aanya"], "narrator"),
    ("rohan", "Rohan", ["Rohan"], "lead"),
    ("elena", "Elena", ["Elena"], "scientist"),
    ("maya", "Maya", ["Maya"], "traveler"),
]

_STOP_WORDS = {
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

_LOC_KEYWORDS = [
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

_OBJ_KEYWORDS = [
    ("golden deer", "obj_golden_deer", "Golden Deer Maricha", "magical golden deer"),
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


def _make_entity_draft(
    eid: str,
    etype: EntityType,
    cname: str,
    aliases: list[str],
    attr_key: str,
    attr_val: str,
) -> ExtractedEntityDraft:
    return ExtractedEntityDraft(
        entity_id=eid,
        entity_type=etype,
        canonical_name=cname,
        aliases=aliases,
        attributes=[AttributeKV(key=attr_key, value=attr_val)],
    )


def _extract_characters(text: str, lower: str) -> list[ExtractedEntityDraft]:
    chars = [
        _make_entity_draft(
            f"char_{tok}", EntityType.CHARACTER, cname, aliases, "role", role_desc
        )
        for tok, cname, aliases, role_desc in _KNOWN_CHAR_PATTERNS
        if re.search(rf"\b{tok}\b", lower)
    ]
    if chars:
        return chars
    found: list[str] = []
    for m in re.finditer(r"\b([A-Z][a-z]{2,15})\b", text):
        w = m.group(1)
        if w not in _STOP_WORDS and w not in found:
            found.append(w)
        if len(found) >= 3:
            break
    found = found or ["Arjun"]
    return [
        _make_entity_draft(
            slug_id(nm, "char"), EntityType.CHARACTER, nm, [], "role", "protagonist"
        )
        for nm in found
    ]


def _extract_locations(lower: str) -> list[ExtractedEntityDraft]:
    locs = [
        _make_entity_draft(
            lid, EntityType.LOCATION, lname, [kw], "environment", env_kind
        )
        for kw, lid, lname, env_kind in _LOC_KEYWORDS
        if re.search(rf"\b{kw}\b", lower)
    ]
    if not locs:
        locs.append(
            _make_entity_draft(
                "loc_main_stage",
                EntityType.LOCATION,
                "Primary Story Setting",
                ["main setting"],
                "environment",
                "interior",
            )
        )
    if len(locs) == 1:
        locs.append(
            _make_entity_draft(
                "loc_secondary_clearing",
                EntityType.LOCATION,
                "Deep Wilderness Clearing",
                ["clearing"],
                "environment",
                "exterior",
            )
        )
    return locs


def _extract_objects(lower: str) -> list[ExtractedEntityDraft]:
    objs: list[ExtractedEntityDraft] = []
    for kw, oid, oname, odesc in _OBJ_KEYWORDS:
        if re.search(rf"\b{kw}\b", lower) and not any(o.entity_id == oid for o in objs):
            objs.append(
                _make_entity_draft(oid, EntityType.OBJECT, oname, [kw], "type", odesc)
            )
    if not objs:
        objs.append(
            _make_entity_draft(
                "obj_relic",
                EntityType.OBJECT,
                "Sacred Story Talisman",
                ["talisman"],
                "type",
                "hero prop",
            )
        )
    return objs


def _build_scene_drafts(
    lead: ExtractedEntityDraft,
    loc1: ExtractedEntityDraft,
    loc2: ExtractedEntityDraft,
    obj: ExtractedEntityDraft,
    weather: str,
) -> list[SceneDraft]:
    s1_sum = f"{lead.canonical_name} and companions encounter the opening conflict around {obj.canonical_name} at {loc1.canonical_name}."
    s2_sum = f"{lead.canonical_name} pursues the quest across {loc2.canonical_name} with {obj.canonical_name}."
    return [
        SceneDraft(
            scene_id="scn_001",
            index=1,
            heading=f"EXT. {loc1.canonical_name.upper()} - DAY",
            location_id=loc1.entity_id,
            location_name=loc1.canonical_name,
            time_of_day="day",
            weather=weather,
            summary=s1_sum,
            mood="dramatic, atmospheric",
        ),
        SceneDraft(
            scene_id="scn_002",
            index=2,
            heading=f"EXT. {loc2.canonical_name.upper()} - DUSK",
            location_id=loc2.entity_id,
            location_name=loc2.canonical_name,
            time_of_day="dusk",
            weather=weather,
            summary=s2_sum,
            mood="urgent, cinematic",
        ),
    ]


def _build_event_drafts(
    characters: list[ExtractedEntityDraft],
    loc1: ExtractedEntityDraft,
    loc2: ExtractedEntityDraft,
    obj: ExtractedEntityDraft,
    scenes: list[SceneDraft],
    w1: str,
    w2: str,
) -> list[EventDraft]:
    lead = characters[0]
    p_ids = [c.entity_id for c in characters]
    ev1_fx = [
        StateEffect(
            entity_id=lead.entity_id, attribute="location", new_value=loc1.entity_id
        ),
        StateEffect(entity_id=lead.entity_id, attribute="wearing", new_value=w1),
        StateEffect(
            entity_id=lead.entity_id, attribute="holding", new_value=obj.entity_id
        ),
        StateEffect(
            entity_id=obj.entity_id, attribute="location", new_value=loc1.entity_id
        ),
        *[
            StateEffect(
                entity_id=c.entity_id, attribute="location", new_value=loc1.entity_id
            )
            for c in characters[1:]
        ],
        *[
            StateEffect(entity_id=c.entity_id, attribute="wearing", new_value="default")
            for c in characters[1:]
        ],
    ]
    ev2_fx = [
        StateEffect(
            entity_id=lead.entity_id, attribute="location", new_value=loc2.entity_id
        ),
        StateEffect(entity_id=lead.entity_id, attribute="wearing", new_value=w2),
        StateEffect(
            entity_id=obj.entity_id, attribute="location", new_value=loc2.entity_id
        ),
        *[
            StateEffect(
                entity_id=c.entity_id, attribute="location", new_value=loc2.entity_id
            )
            for c in characters[1:]
        ],
    ]
    return [
        EventDraft(
            event_id="evt_001",
            story_order=10,
            scene_id="scn_001",
            summary=scenes[0].summary,
            participants=p_ids,
            effects=ev1_fx,
        ),
        EventDraft(
            event_id="evt_002",
            story_order=20,
            scene_id="scn_002",
            summary=scenes[1].summary,
            participants=p_ids,
            effects=ev2_fx,
        ),
    ]


def extract_entities_from_story(
    story_text: str,
) -> tuple[list[ExtractedEntityDraft], list[SceneDraft], list[EventDraft]]:
    """Parse story text / idea into rich Characters, Locations, Objects, Scenes, and Events."""
    story_text = normalize_indian_epic_names(story_text)
    lines = [
        ln
        for ln in story_text.strip().splitlines()
        if not ln.strip().lower().startswith("visual style:")
    ]
    text = "\n".join(lines).strip() or story_text.strip()
    lower = text.lower()
    characters = _extract_characters(text, lower)
    locations = _extract_locations(lower)
    objects = _extract_objects(lower)
    w1 = "trenchcoat" if "trenchcoat" in lower or "coat" in lower else "default"
    w2 = "formal_suit" if "suit" in lower or "tuxedo" in lower else w1
    weather = "rain" if "rain" in lower or "monsoon" in lower else "clear"
    scenes = _build_scene_drafts(
        characters[0], locations[0], locations[-1], objects[0], weather
    )
    events = _build_event_drafts(
        characters, locations[0], locations[-1], objects[0], scenes, w1, w2
    )
    return [*characters, *locations, *objects], scenes, events

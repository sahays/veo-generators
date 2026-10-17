"""Indian epic name normalizers and entity ID slug/fuzzy matching helpers."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ...schema import EntityType

_EPIC_NAME_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bRama\b"), "Ram"),
    (re.compile(r"\brama\b"), "ram"),
    (re.compile(r"\bRAMA\b"), "RAM"),
    (re.compile(r"\bLakshmana\b"), "Lakshman"),
    (re.compile(r"\blakshmana\b"), "lakshman"),
    (re.compile(r"\bLAKSHMANA\b"), "LAKSHMAN"),
    (re.compile(r"\bRavana\b"), "Ravan"),
    (re.compile(r"\bravana\b"), "ravan"),
    (re.compile(r"\bRAVANA\b"), "RAVAN"),
    (re.compile(r"\bSurpanakha\b"), "Shurpanakha"),
    (re.compile(r"\bsurpanakha\b"), "shurpanakha"),
    (re.compile(r"\bSURPANAKHA\b"), "SHURPANAKHA"),
]

_CANONICAL_ENTITY_ID_MAP: dict[str, str] = {
    "char_rama": "char_ram",
    "char_lord_rama": "char_ram",
    "char_lord_ram": "char_ram",
    "char_shri_ram": "char_ram",
    "char_shri_rama": "char_ram",
    "char_prince_ram": "char_ram",
    "char_prince_rama": "char_ram",
    "char_lakshmana": "char_lakshman",
    "char_prince_lakshman": "char_lakshman",
    "char_prince_lakshmana": "char_lakshman",
    "char_ravana": "char_ravan",
    "char_king_ravana": "char_ravan",
    "char_king_ravan": "char_ravan",
    "char_demon_king_ravana": "char_ravan",
    "char_demon_king_ravan": "char_ravan",
    "char_surpanakha": "char_shurpanakha",
    "char_demoness_surpanakha": "char_shurpanakha",
    "char_demoness_shurpanakha": "char_shurpanakha",
    "char_goddess_sita": "char_sita",
    "char_mata_sita": "char_sita",
    "char_princess_sita": "char_sita",
    "char_janaki": "char_sita",
    "char_demi_god_vulture_jatayu": "char_jatayu",
    "char_vulture_jatayu": "char_jatayu",
    "char_vulture_king_jatayu": "char_jatayu",
    "obj_jatayu": "char_jatayu",
    "char_devotee_shabari": "char_shabari",
    "char_mata_shabari": "char_shabari",
}

_HONORIFIC_STOP_TOKENS = {
    "lord",
    "king",
    "queen",
    "prince",
    "princess",
    "goddess",
    "mata",
    "shri",
    "sri",
    "demon",
    "demoness",
    "demi",
    "god",
    "vulture",
    "devotee",
    "sage",
    "dr",
    "detective",
    "captain",
    "agent",
}


def normalize_indian_epic_names(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, repl in _EPIC_NAME_REPLACEMENTS:
        out = pat.sub(repl, out)
    return out


def normalize_entity_id(eid: str, entity_type: EntityType | None = None) -> str:
    clean = normalize_indian_epic_names(eid.strip()).lower()
    clean = re.sub(r"[^a-z0-9]+", "_", clean).strip("_")
    if entity_type == EntityType.CHARACTER and not clean.startswith("char_"):
        clean = f"char_{clean.removeprefix('obj_').removeprefix('loc_')}"
    elif entity_type == EntityType.LOCATION and not clean.startswith("loc_"):
        clean = f"loc_{clean.removeprefix('char_').removeprefix('obj_')}"
    elif entity_type == EntityType.OBJECT and not clean.startswith("obj_"):
        clean = f"obj_{clean.removeprefix('char_').removeprefix('loc_')}"
    return _CANONICAL_ENTITY_ID_MAP.get(clean, clean)


def strip_honorifics(name: str) -> str:
    norm = normalize_indian_epic_names(name).strip().lower()
    tokens = [
        t
        for t in re.split(r"[^a-z0-9]+", norm)
        if t and t not in _HONORIFIC_STOP_TOKENS
    ]
    return " ".join(tokens) if tokens else norm


def slug_id(text: str, prefix: str) -> str:
    norm = normalize_indian_epic_names(text)
    clean = re.sub(r"[^a-z0-9]+", "_", norm.strip().lower()).strip("_")
    raw_id = f"{prefix}_{clean or 'item'}"
    return _CANONICAL_ENTITY_ID_MAP.get(raw_id, raw_id)


def name_similarity(a: str, b: str) -> float:
    a_clean = normalize_indian_epic_names(a).strip().lower()
    b_clean = normalize_indian_epic_names(b).strip().lower()
    if not a_clean or not b_clean:
        return 0.0
    a_core = strip_honorifics(a_clean)
    b_core = strip_honorifics(b_clean)
    scores = [fuzz.ratio(a_clean, b_clean)]
    if a_core and b_core:
        scores.append(fuzz.ratio(a_core, b_core))
        if len(a_core) >= 3 and len(b_core) >= 3:
            scores.append(fuzz.token_set_ratio(a_core, b_core))
    return max(scores)

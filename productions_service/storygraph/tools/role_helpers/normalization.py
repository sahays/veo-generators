"""Indian epic name normalizers and entity ID slug/fuzzy matching helpers."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ...schema import CastInShot, DialogueLine, EntityType
from .models import ShotDraft

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


def partition_scene_dialogues(
    shots: list[ShotDraft],
    dlg_ids: list[str],
    dlg_by_id: dict[str, DialogueLine],
) -> list[list[str]]:
    """Partition scene `dlg_ids` across `shots` with zero dropped lines and 1-speaker preference."""
    n_shots = len(shots)
    if n_shots == 0:
        return []
    valid_dlgs = [d for d in dlg_ids if d in dlg_by_id]
    if not valid_dlgs:
        return [[] for _ in shots]
    if n_shots == 1:
        return [valid_dlgs]
    assigned = [[d for d in sh.dialogue_ids if d in dlg_by_id] for sh in shots]
    flat = [d for bucket in assigned for d in bucket]
    has_empty = any(not b for b in assigned)
    over_words = any(
        sum(len(dlg_by_id[d].text.split()) for d in b) > 22 for b in assigned
    )
    multi_sp = any(len({dlg_by_id[d].speaker_id for d in b}) > 1 for b in assigned)
    if flat == valid_dlgs and not over_words and not (has_empty and multi_sp):
        return assigned
    if len(valid_dlgs) == 1:
        return [valid_dlgs, *([[]] * (n_shots - 1))]
    out: list[list[str]] = []
    k, rem = divmod(len(valid_dlgs), n_shots)
    front_heavy = sum(len(dlg_by_id[d].text.split()) for d in valid_dlgs[: k + 1]) > 22
    cursor = 0
    for i in range(n_shots):
        extra = (i >= n_shots - rem) if front_heavy else (i < rem)
        step = k + (1 if extra else 0)
        out.append(valid_dlgs[cursor : cursor + step])
        cursor += step
    return out


def deduplicate_cast_positions(
    cast_by_id: dict[str, CastInShot],
    prev_positions: dict[str, str],
) -> dict[str, CastInShot]:
    """Enforce 180-degree screen-slot continuity across shots and deduplicate foreground positions."""
    slot_order = ("left", "right", "center")
    used_fg: set[str] = set()
    resolved: dict[str, CastInShot] = {}
    for cid, c in cast_by_id.items():
        desired = prev_positions.get(cid, c.position)
        if desired == "background":
            resolved[cid] = c.model_copy(update={"position": "background"})
            continue
        if len(cast_by_id) > 1 and desired in used_fg:
            desired = next((s for s in slot_order if s not in used_fg), desired)
        used_fg.add(desired)
        prev_positions[cid] = desired
        resolved[cid] = c.model_copy(update={"position": desired})  # type: ignore[arg-type]
    return resolved


def expand_overbudget_shot_buckets(
    shots: list[ShotDraft],
    buckets: list[list[str]],
    dlg_by_id: dict[str, DialogueLine],
    max_words: int = 22,
) -> list[tuple[ShotDraft, list[str]]]:
    """Split any `(ShotDraft, dlg_ids)` pair exceeding `max_words` so every shot obeys V8 (2.8 words/s)."""
    pairs: list[tuple[ShotDraft, list[str]]] = []
    for sh, dlgs in zip(shots, buckets):
        words = sum(len(dlg_by_id[d].text.split()) for d in dlgs if d in dlg_by_id)
        if words > max_words and len(dlgs) >= 2:
            mid = max(1, len(dlgs) // 2)
            pairs.append((sh, dlgs[:mid]))
            pairs.append(
                (sh.model_copy(update={"continue_from_last_frame": True}), dlgs[mid:])
            )
        else:
            pairs.append((sh, dlgs))
    return pairs

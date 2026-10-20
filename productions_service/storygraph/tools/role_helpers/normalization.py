"""Indian epic name normalizers and entity ID slug/fuzzy matching helpers."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from ...schema import ActionBeat, CastInShot, DialogueLine, EntityType, InteractionStep
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
            desired = next((s for s in slot_order if s not in used_fg), "background")
        if desired != "background":
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


def _group_steps_into_clip_windows(
    steps: list[InteractionStep],
    max_window_s: float = 10.0,
    max_steps_per_shot: int = 3,
) -> list[list[InteractionStep]]:
    """Pack sequential `InteractionStep` items into 8.0–10.0s clip windows (up to 3 steps per clip)."""
    windows: list[list[InteractionStep]] = []
    cur: list[InteractionStep] = []
    cur_dur = 0.0
    for st in steps:
        hint = max(2.5, min(5.0, float(st.duration_hint_s or 3.5)))
        if cur and (
            len(cur) >= max_steps_per_shot or (cur_dur + hint) > max_window_s + 0.5
        ):
            windows.append(cur)
            cur = []
            cur_dur = 0.0
        cur.append(st)
        cur_dur += hint
    if cur:
        windows.append(cur)
    return windows


def _build_window_shot(
    template_sh: ShotDraft,
    win: list[InteractionStep],
    location_id: str,
    is_continuation: bool,
) -> ShotDraft:
    """Build an 8.0–10.0s `ShotDraft` covering a 1–3 step window `win`."""
    raw_sum = sum(max(2.5, min(5.0, float(st.duration_hint_s or 3.5))) for st in win)
    dur = max(8.0 if len(win) >= 2 else 6.0, min(10.0, round(raw_sum, 1)))
    step_dur = round(dur / len(win), 2)
    beats: list[ActionBeat] = []
    for idx, st in enumerate(win):
        t0 = round(idx * step_dur, 2)
        t1 = round(dur if idx == len(win) - 1 else (idx + 1) * step_dur, 2)
        subj = [
            sid for sid in (st.actor_id, st.target_id) if sid and sid != location_id
        ]
        mech = st.contact_mechanics or st.supported_by
        desc = f"{st.action} ({mech})" if mech else st.action
        beats.append(
            ActionBeat(
                t_start_s=t0,
                t_end_s=max(t0 + 0.5, t1),
                description=desc,
                subject_ids=subj,
                pre_state=st.pre_state,
                post_state=st.post_state,
            )
        )
    return template_sh.model_copy(
        update={
            "duration_s": dur,
            "beats": beats,
            "continue_from_last_frame": is_continuation,
        }
    )


def expand_unhurried_shots(
    shots: list[ShotDraft],
    steps: list[InteractionStep],
    location_id: str,
    is_live_llm: bool,
) -> list[ShotDraft]:
    """Pace shots into 8–10s video clip windows, splitting multi-action scenes across 8–10s clips."""
    expanded: list[ShotDraft] = []
    for sh in shots:
        if len(sh.beats) > 3:
            for b_idx in range(0, len(sh.beats), 3):
                chunk = sh.beats[b_idx : b_idx + 3]
                expanded.append(
                    sh.model_copy(
                        update={
                            "beats": chunk,
                            "duration_s": max(
                                8.0, min(10.0, float(sh.duration_s or 8.0))
                            ),
                            "continue_from_last_frame": True
                            if b_idx > 0
                            else sh.continue_from_last_frame,
                        }
                    )
                )
        else:
            expanded.append(sh)
    windows = _group_steps_into_clip_windows(steps)
    if is_live_llm and len(windows) > len(expanded) and expanded:
        return [
            _build_window_shot(
                expanded[min(w_idx, len(expanded) - 1)],
                win,
                location_id,
                is_continuation=(w_idx > 0),
            )
            for w_idx, win in enumerate(windows)
        ]
    return expanded

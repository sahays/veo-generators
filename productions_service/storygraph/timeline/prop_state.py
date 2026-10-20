"""Per-clip prop states from graph facts, in plain words (never placeholders or fabricated
physics text).

For each clip edge (opening = before the clip's first Event, closing = after its last):
`supported_by` is the prop's own location (a location-like `supported_by`/`sub_location`
fact, else the latest earlier one), `condition` its state words (`orientation` and
condition-like `sub_location`, e.g. 'closed'), `location` its room, `held_by` its holder.
`consumed_by` names who ate it when the clip's Events end its existence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from ..repo import Repo
from ..schema import EntityType, Event, InteractionStep, Scene, Shot, StateFact
from ..state import holders_at, state_at
from .clip_events import ClipWindow
from .lifecycle import Lifecycle, is_death
from .placement import is_condition

_PLACE_ATTRS: Final[tuple[str, ...]] = ("supported_by", "sub_location")
_EAT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:eat|ate|swallow|munch|gobbl|chomp|devour|gulp|nibbl|chew|consum)\w*",
    re.IGNORECASE,
)


def _place(facts: dict[str, str]) -> str:
    """Own location from current facts: first location-like place attribute."""
    vals = (facts.get(a, "") for a in _PLACE_ATTRS)
    return next((v for v in vals if v.strip() and not is_condition(v)), "")


def _condition(facts: dict[str, str]) -> str:
    parts = [facts.get("orientation", "")]
    parts += [facts.get(a, "") for a in _PLACE_ATTRS if is_condition(facts.get(a, ""))]
    return ", ".join(dict.fromkeys(p.strip() for p in parts if p.strip()))


def _last_place(history: list[StateFact], order: int) -> str:
    """Latest location-like place fact that started at or before `order` (O(n))."""
    best: StateFact | None = None
    for f in history:
        if (
            f.attribute in _PLACE_ATTRS
            and f.valid_from_order <= order
            and not is_condition(f.value)
            and (best is None or f.valid_from_order >= best.valid_from_order)
        ):
            best = f
    return best.value if best else ""


def _edge(
    facts: dict[str, str], history: list[StateFact], order: int
) -> dict[str, str]:
    return {
        "supported_by": _place(facts) or _last_place(history, order),
        "condition": _condition(facts),
        "orientation": facts.get("orientation", ""),
        "location": facts.get("location", ""),
    }


def _consumer(
    pid: str, events: Iterable[Event], names: dict[str, str], texts: list[str]
) -> str:
    """Name of the character who eats `pid` in `events` ('' when not an eating death)."""
    for ev in events:
        if any(
            e.entity_id == pid
            and e.attribute == "alive_present"
            and is_death(e.new_value)
            for e in ev.effects
        ):
            return _eater(" ".join([ev.summary, *texts]), names)
    return ""


def _eater(text: str, names: dict[str, str]) -> str:
    """Closest non-possessive character name before the first eating verb."""
    verb = _EAT_RE.search(text)
    if verb is None:
        return ""
    head = text[: verb.start()]
    best, best_pos = "", -1
    for name in names.values():
        for m in re.finditer(rf"\b{re.escape(name)}\b(?!['\u2019]s)", head):
            if m.start() > best_pos:
                best, best_pos = name, m.start()
    return best


def _steps_by_prop(
    scene: Scene, step_indices: list[int], prop_ids: list[str]
) -> dict[str, list[InteractionStep]]:
    wanted, chosen = set(prop_ids), set(step_indices)
    out: dict[str, list[InteractionStep]] = {}
    for st in scene.interaction_steps:
        if st.target_id in wanted and st.step_index in chosen:
            out.setdefault(st.target_id, []).append(st)
    return out


def _prior_post_states(scene: Scene, first_step: int) -> dict[str, str]:
    """prop_id -> post_state of the last step before the clip that targeted it."""
    out: dict[str, str] = {}
    for st in sorted(scene.interaction_steps, key=lambda s: s.step_index):
        if st.step_index < first_step and st.target_id and st.post_state.strip():
            out[st.target_id] = st.post_state.strip()
    return out


def _character_names(repo: Repo) -> dict[str, str]:
    chars = repo.list_entities(entity_type=EntityType.CHARACTER)
    return {c.id: c.canonical_name for c in chars}


def _with_prefix(prefix: str, values: dict[str, str]) -> dict[str, str]:
    return {f"{prefix}{k}": v for k, v in values.items()}


def resolve_prop_states_for_shot(
    repo: Repo,
    scene: Scene,
    shot: Shot,
    window: ClipWindow,
    lifecycles: dict[str, Lifecycle] | None = None,
) -> dict[str, dict[str, str]]:
    """Per-clip prop states (plain data, '' when unknown); `end_*` keys are the closing edge."""
    clip = next((c for c in scene.clips if c.clip_index == shot.clip_index), None)
    steps = _steps_by_prop(scene, clip.step_indices if clip else [], shot.prop_ids)
    prior = _prior_post_states(scene, min(clip.step_indices, default=0) if clip else 0)
    holders = (holders_at(repo, window.open_at), holders_at(repo, window.close_at))
    in_clip = [
        e for e in repo.list_events(scene_id=scene.id) if e.id in window.event_ids
    ]
    names, life = _character_names(repo), lifecycles or {}
    out: dict[str, dict[str, str]] = {}
    for pid in shot.prop_ids:
        hist = repo.list_state_facts(entity_id=pid)
        o_f, c_f = (
            state_at(repo, pid, window.open_at),
            state_at(repo, pid, window.close_at),
        )
        lc, mine = life.get(pid, Lifecycle(pid)), steps.get(pid, [])
        texts = [f"{s.action} {s.detail}" for s in mine]
        out[pid] = {
            **_edge(o_f, hist, window.open_at),
            **_with_prefix("end_", _edge(c_f, hist, window.close_at)),
            "held_by": holders[0].get(pid, ""),
            "end_held_by": holders[1].get(pid, ""),
            "alive_start": str(lc.alive_at(window.open_at)).lower(),
            "alive_end": str(lc.alive_at(window.close_at)).lower(),
            "consumed_by": _consumer(pid, in_clip, names, texts),
            "pre_state": mine[0].pre_state if mine else "",
            "post_state": mine[-1].post_state if mine else "",
            "opening_state": "; ".join(
                p for p in (o_f.get("orientation", ""), prior.get(pid) or "") if p
            ),
        }
    return out

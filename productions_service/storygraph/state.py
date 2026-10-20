"""Deterministic State Engine: rebuilds StateFact intervals from Events and resolves Appearances.

Story time uses integer `story_order`s with post-state semantics: `state_at(o)` is the state
*after* the Event at order `o`, so the state *before* that Event is `state_at(o - 1)`.
Shots are aligned to the Events their clip plays (`timeline.clip_events`), never to their
position in the scene: `Shot.story_order` is the order of the clip's first Event and
`Shot.covers_event_ids` its Events; opening state is read *before* that Event.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .errors import ValidationFailed
from .repo import Repo
from .schema import Appearance, Event, Role, Scene, StateFact, Status
from .timeline.clip_events import ClipWindow, scene_clip_windows

_log = logging.getLogger(__name__)


def _log_state(what: str, why: str, how: str) -> None:
    _log.info(
        "state_rebuild",
        extra={
            "who": "storygraph.state",
            "where": "rebuild_state_facts",
            "what": what,
            "when": datetime.now(UTC).isoformat(),
            "why": why,
            "how": how,
        },
    )


def _legacy_order(index_in_scene: int, base_order: int, num_events: int) -> int:
    """Positional order for shots with no screenwriter clip (pre-clip graphs only)."""
    return base_order + min(max(0, index_in_scene - 1), max(0, num_events - 1))


def _sync_scene_shots(repo: Repo, sc: Scene, sc_events: list[Event]) -> None:
    """Align each shot's `story_order`/`covers_event_ids` with the Events its clip plays."""
    windows = scene_clip_windows(sc, sc_events)
    base_order = sc_events[0].story_order if sc_events else sc.index * 10
    for sh in repo.list_shots(scene_id=sc.id):
        win = windows.get(sh.clip_index) if sh.clip_index is not None else None
        update = (
            {"story_order": win.first_order, "covers_event_ids": list(win.event_ids)}
            if win is not None
            else {
                "story_order": _legacy_order(
                    sh.index_in_scene, base_order, len(sc_events)
                )
            }
        )
        if any(getattr(sh, k) != v for k, v in update.items()):
            repo.put_shot(sh.model_copy(update=update))


def _sync_scene_event_ids(repo: Repo, sc: Scene, sc_events: list[Event]) -> None:
    """`Scene.event_ids` mirrors the scene's own Events in story order (no stale ids)."""
    ids = [e.id for e in sc_events]
    if sc.event_ids != ids:
        repo.put_scene(sc.model_copy(update={"event_ids": ids}))


def _renumber_events(repo: Repo, sc: Scene, sc_events: list[Event]) -> list[Event]:
    base_order = sc.index * 10
    out: list[Event] = []
    for e_idx, ev in enumerate(sc_events):
        if ev.story_order != base_order + e_idx:
            ev = repo.put_event(
                ev.model_copy(update={"story_order": base_order + e_idx})
            )
        out.append(ev)
    return out


def normalize_scene_timeline(repo: Repo) -> None:
    """Normalize event orders into scene bands, then align shots and scene event ids."""
    scenes = repo.list_scenes()
    events_by_scene = {sc.id: repo.list_events(scene_id=sc.id) for sc in scenes}
    needs_event_norm = any(
        e.story_order < sc.index * 10 for sc in scenes for e in events_by_scene[sc.id]
    )
    for sc in scenes:
        sc_events = sorted(events_by_scene[sc.id], key=lambda e: (e.story_order, e.id))
        if needs_event_norm:
            sc_events = _renumber_events(repo, sc, sc_events)
        _sync_scene_event_ids(repo, sc, sc_events)
        _sync_scene_shots(repo, sc, sc_events)


def _new_fact(
    seq: int, ev: Event, entity_id: str, attribute: str, value: str
) -> StateFact:
    return StateFact(
        id=f"sf_{seq:04d}",
        created_by=Role.PIPELINE,
        entity_id=entity_id,
        attribute=attribute,
        value=value,
        valid_from_order=ev.story_order,
        valid_to_order=None,
        caused_by_event_id=ev.id,
        status=Status.APPROVED,
    )


def rebuild_state_facts(repo: Repo) -> list[StateFact]:
    """Replay Events in story_order into half-open [from, to) StateFact intervals.

    An effect that restates the current value is a no-op and opens no new interval.
    """
    normalize_scene_timeline(repo)
    events = sorted(repo.list_events(), key=lambda e: (e.story_order, e.id))
    open_facts: dict[tuple[str, str], StateFact] = {}
    closed: list[StateFact] = []
    seq, skipped = 0, 0
    for ev in events:
        for eff in ev.effects:
            key = (eff.entity_id, eff.attribute)
            prev = open_facts.get(key)
            if prev is not None and prev.value == eff.new_value:
                skipped += 1
                continue
            if prev is not None:
                closed.append(
                    open_facts.pop(key).model_copy(
                        update={"valid_to_order": ev.story_order}
                    )
                )
            if eff.new_value is not None:
                seq += 1
                open_facts[key] = _new_fact(
                    seq, ev, eff.entity_id, eff.attribute, eff.new_value
                )
    all_facts = closed + list(open_facts.values())
    repo.replace_all_state_facts(all_facts)
    _log_state(
        f"{len(all_facts)} facts", f"{skipped} no-op effects dropped", "event replay"
    )
    return all_facts


def _active(f: StateFact, story_order: int) -> bool:
    return f.valid_from_order <= story_order and (
        f.valid_to_order is None or story_order < f.valid_to_order
    )


def state_at(repo: Repo, entity_id: str, story_order: int) -> dict[str, str]:
    """Return active `{attribute: value}` for `entity_id` after the Event at `story_order`."""
    out: dict[str, str] = {}
    for f in repo.list_state_facts(entity_id=entity_id):
        if _active(f, story_order):
            out[f.attribute] = f.value
    return out


def state_before(repo: Repo, entity_id: str, story_order: int) -> dict[str, str]:
    """State just before the Event at `story_order` (integer orders)."""
    return state_at(repo, entity_id, story_order - 1)


def holders_at(repo: Repo, story_order: int) -> dict[str, str]:
    """`held object id -> holder id` at `story_order` (one pass over holding facts)."""
    return {
        f.value: f.entity_id
        for f in repo.list_state_facts()
        if f.attribute == "holding" and f.value and _active(f, story_order)
    }


def window_states(
    repo: Repo, entity_ids: list[str], win: ClipWindow
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """(opening, closing) state per entity for a clip window."""
    opening = {eid: state_at(repo, eid, win.open_at) for eid in entity_ids}
    closing = {eid: state_at(repo, eid, win.close_at) for eid in entity_ids}
    return opening, closing


def appearance_for(repo: Repo, entity_id: str, story_order: int) -> Appearance:
    """Resolve the active Appearance for `entity_id` at `story_order` based on `wearing` state."""
    st = state_at(repo, entity_id, story_order)
    wanted_labels = [lbl for lbl in (st.get("wearing"), "default") if lbl]
    candidates = [
        a
        for a in repo.list_appearances(entity_id=entity_id)
        if a.status in (Status.APPROVED, Status.PROPOSED, Status.DRAFT)
    ]
    # Prefer APPROVED first, then highest version
    candidates.sort(
        key=lambda a: (a.status == Status.APPROVED, a.version), reverse=True
    )
    for label in wanted_labels:
        for a in candidates:
            if a.state_label == label:
                return a
    if candidates:
        return candidates[0]
    raise ValidationFailed([f"No appearance for {entity_id} at order {story_order}"])

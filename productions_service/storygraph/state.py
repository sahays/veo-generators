"""Deterministic State Engine: rebuilds StateFact intervals from Events and resolves Appearances."""

from __future__ import annotations

from .errors import ValidationFailed
from .repo import Repo
from .schema import Appearance, Role, StateFact, Status


def _normalize_scene_shots(
    repo: Repo, sc_id: str, base_order: int, num_events: int
) -> None:
    """Align shot `story_order` with its corresponding scene event offset `[0, num_events - 1]`."""
    max_offset = max(0, num_events - 1)
    for sh in repo.list_shots(scene_id=sc_id):
        offset = min(max(0, sh.index_in_scene - 1), max_offset)
        target_order = base_order + offset
        if sh.story_order != target_order:
            repo.put_shot(sh.model_copy(update={"story_order": target_order}))


def normalize_scene_timeline(repo: Repo) -> None:
    """Normalize scene event and shot story_orders into [sc.index * 10, (sc.index + 1) * 10) bands."""
    scenes = repo.list_scenes()
    if not scenes:
        return
    needs_event_norm = any(
        e.story_order < sc.index * 10
        for sc in scenes
        for e in repo.list_events(scene_id=sc.id)
    )
    for sc in scenes:
        base_order = sc.index * 10
        sc_events = repo.list_events(scene_id=sc.id)
        if needs_event_norm:
            for e_idx, ev in enumerate(sc_events):
                if ev.story_order != base_order + e_idx:
                    repo.put_event(
                        ev.model_copy(update={"story_order": base_order + e_idx})
                    )
            _normalize_scene_shots(repo, sc.id, base_order, len(sc_events))
        elif sc_events and all(
            ev.story_order == base_order + idx for idx, ev in enumerate(sc_events)
        ):
            _normalize_scene_shots(repo, sc.id, base_order, len(sc_events))


def rebuild_state_facts(repo: Repo) -> list[StateFact]:
    """Deterministically replay Events in story_order to derive half-open [from, to) StateFact intervals."""
    normalize_scene_timeline(repo)
    events = sorted(repo.list_events(), key=lambda e: (e.story_order, e.id))
    open_facts: dict[tuple[str, str], StateFact] = {}
    closed: list[StateFact] = []
    seq = 0

    for ev in events:
        for eff in ev.effects:
            key = (eff.entity_id, eff.attribute)
            if key in open_facts:
                prev = open_facts.pop(key)
                closed.append(
                    prev.model_copy(update={"valid_to_order": ev.story_order})
                )
            if eff.new_value is not None:
                seq += 1
                open_facts[key] = StateFact(
                    id=f"sf_{seq:04d}",
                    created_by=Role.PIPELINE,
                    entity_id=eff.entity_id,
                    attribute=eff.attribute,
                    value=eff.new_value,
                    valid_from_order=ev.story_order,
                    valid_to_order=None,
                    caused_by_event_id=ev.id,
                    status=Status.APPROVED,
                )

    all_facts = closed + list(open_facts.values())
    repo.replace_all_state_facts(all_facts)
    return all_facts


def state_at(repo: Repo, entity_id: str, story_order: int) -> dict[str, str]:
    """Return active `{attribute: value}` for `entity_id` at `story_order`."""
    facts = repo.list_state_facts(entity_id=entity_id)
    out: dict[str, str] = {}
    for f in facts:
        if f.valid_from_order <= story_order and (
            f.valid_to_order is None or story_order < f.valid_to_order
        ):
            out[f.attribute] = f.value
    return out


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

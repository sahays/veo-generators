"""Deterministic State Engine: rebuilds StateFact intervals from Events and resolves Appearances."""

from __future__ import annotations

from .errors import ValidationFailed
from .repo import Repo
from .schema import Appearance, Role, StateFact, Status


def rebuild_state_facts(repo: Repo) -> list[StateFact]:
    """Deterministically replay Events in story_order to derive half-open [from, to) StateFact intervals."""
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
    """Resolve the active Appearance for `entity_id` at `story_order` based on `wearing` / `injury` state."""
    st = state_at(repo, entity_id, story_order)
    wanted_labels = [
        lbl for lbl in (st.get("wearing"), st.get("injury"), "default") if lbl
    ]
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
